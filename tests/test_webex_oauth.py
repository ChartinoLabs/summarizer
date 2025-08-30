"""Tests for Webex OAuth 2.0 authentication."""

import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import responses

from summarizer.webex.oauth import (
    OAuthCallbackServer,
    WebexOAuthApp,
    WebexOAuthClient,
    WebexOAuthCredentials,
)


class TestWebexOAuthCredentials:
    """Test cases for OAuth credentials dataclass."""

    def test_is_expired_false_for_future_expiry(self) -> None:
        """Non-expired credentials should return False."""
        future = datetime.now(UTC) + timedelta(hours=1)
        creds = WebexOAuthCredentials(
            access_token="token",
            refresh_token="refresh",
            expires_at=future
        )
        assert not creds.is_expired()

    def test_is_expired_true_for_past_expiry(self) -> None:
        """Expired credentials should return True."""
        past = datetime.now(UTC) - timedelta(hours=1)
        creds = WebexOAuthCredentials(
            access_token="token",
            refresh_token="refresh", 
            expires_at=past
        )
        assert creds.is_expired()

    def test_is_expired_with_buffer(self) -> None:
        """Should account for buffer time in expiry check."""
        near_future = datetime.now(UTC) + timedelta(minutes=3)
        creds = WebexOAuthCredentials(
            access_token="token",
            refresh_token="refresh",
            expires_at=near_future
        )
        # With default 5-minute buffer, should be considered expired
        assert creds.is_expired()
        # With 1-minute buffer, should not be expired
        assert not creds.is_expired(buffer_minutes=1)

    def test_serialization_roundtrip(self) -> None:
        """Credentials should serialize and deserialize correctly."""
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        original = WebexOAuthCredentials(
            access_token="access123",
            refresh_token="refresh456",
            expires_at=expires_at,
            token_type="Bearer",
            scope="spark:messages_read spark:rooms_read"
        )
        
        # Serialize to dict
        data = original.to_dict()
        assert isinstance(data["expires_at"], str)
        
        # Deserialize back
        restored = WebexOAuthCredentials.from_dict(data)
        
        assert restored.access_token == original.access_token
        assert restored.refresh_token == original.refresh_token
        assert restored.expires_at == original.expires_at
        assert restored.token_type == original.token_type
        assert restored.scope == original.scope


class TestWebexOAuthApp:
    """Test cases for OAuth app configuration."""

    def test_default_scopes(self) -> None:
        """Should have default scopes if none provided."""
        app = WebexOAuthApp(client_id="id", client_secret="secret")
        expected_scopes = [
            "spark:messages_read",
            "spark:rooms_read",
            "openid", 
            "email",
            "profile"
        ]
        assert app.scopes == expected_scopes

    def test_custom_scopes(self) -> None:
        """Should use custom scopes if provided."""
        custom_scopes = ["spark:messages_read", "openid"]
        app = WebexOAuthApp(
            client_id="id",
            client_secret="secret", 
            scopes=custom_scopes
        )
        assert app.scopes == custom_scopes


class TestOAuthCallbackServer:
    """Test cases for OAuth callback server."""

    def test_server_start_and_stop(self) -> None:
        """Should start and stop server correctly."""
        server = OAuthCallbackServer()
        
        # Start server
        callback_url = server.start()
        assert callback_url.startswith("http://localhost:")
        assert "/callback" in callback_url
        
        # Server should be running
        assert server.server is not None
        assert server.server_thread is not None
        
        # Stop server
        server.stop()
        assert server.server is None

    def test_server_port_fallback(self) -> None:
        """Should find available port if default is busy."""
        # Start first server on default port
        server1 = OAuthCallbackServer(port=8080)
        callback_url1 = server1.start()
        
        try:
            # Start second server, should use different port
            server2 = OAuthCallbackServer(port=8080)
            callback_url2 = server2.start()
            
            try:
                assert callback_url1 != callback_url2
                # Both should be valid callback URLs
                assert "localhost:" in callback_url1
                assert "localhost:" in callback_url2
            finally:
                server2.stop()
        finally:
            server1.stop()


class TestWebexOAuthClient:
    """Test cases for OAuth client."""

    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.app_config = WebexOAuthApp(
            client_id="test_client_id",
            client_secret="test_client_secret"
        )
        
        # Use temporary directory for credentials
        self.temp_dir = tempfile.mkdtemp()
        self.client = WebexOAuthClient(self.app_config)
        # Override credentials path to use temp directory
        self.client.credentials_file = Path(self.temp_dir) / "test_credentials.json"

    def test_generate_pkce_params(self) -> None:
        """Should generate valid PKCE parameters."""
        verifier, challenge = self.client._generate_pkce_params()
        
        # Verifier should be base64url encoded string
        assert isinstance(verifier, str)
        assert len(verifier) >= 43  # Minimum length for PKCE
        
        # Challenge should be different from verifier
        assert isinstance(challenge, str)
        assert challenge != verifier

    def test_get_authorization_url(self) -> None:
        """Should generate proper authorization URL."""
        auth_url, code_verifier = self.client.get_authorization_url()
        
        assert auth_url.startswith("https://webexapis.com/v1/authorize")
        assert "client_id=test_client_id" in auth_url
        assert "response_type=code" in auth_url
        assert "code_challenge=" in auth_url
        assert "code_challenge_method=S256" in auth_url
        assert "state=" in auth_url
        assert isinstance(code_verifier, str)

    @responses.activate
    def test_exchange_code_for_tokens_success(self) -> None:
        """Should successfully exchange code for tokens."""
        # Mock successful token response
        token_response = {
            "access_token": "access123",
            "refresh_token": "refresh456", 
            "expires_in": 1209600,  # 14 days
            "token_type": "Bearer",
            "scope": "spark:messages_read spark:rooms_read"
        }
        responses.add(
            responses.POST,
            "https://webexapis.com/v1/access_token",
            json=token_response,
            status=200
        )
        
        credentials = self.client.exchange_code_for_tokens("auth_code", "code_verifier")
        
        assert credentials.access_token == "access123"
        assert credentials.refresh_token == "refresh456"
        assert credentials.token_type == "Bearer"
        assert credentials.scope == "spark:messages_read spark:rooms_read"
        # Should expire approximately 14 days from now
        expected_expiry = datetime.now(UTC) + timedelta(seconds=1209600)
        assert abs((credentials.expires_at - expected_expiry).total_seconds()) < 60

    @responses.activate
    def test_refresh_access_token_success(self) -> None:
        """Should successfully refresh access token."""
        # Create existing credentials
        old_expires = datetime.now(UTC) + timedelta(hours=1)
        old_credentials = WebexOAuthCredentials(
            access_token="old_access",
            refresh_token="refresh456",
            expires_at=old_expires
        )
        
        # Mock successful refresh response
        refresh_response = {
            "access_token": "new_access",
            "expires_in": 1209600,
            "token_type": "Bearer"
        }
        responses.add(
            responses.POST,
            "https://webexapis.com/v1/access_token", 
            json=refresh_response,
            status=200
        )
        
        new_credentials = self.client.refresh_access_token(old_credentials)
        
        assert new_credentials.access_token == "new_access"
        assert new_credentials.refresh_token == "refresh456"  # Should keep old refresh token
        assert new_credentials.expires_at > old_expires

    def test_save_and_load_credentials(self) -> None:
        """Should save and load credentials correctly."""
        expires_at = datetime.now(UTC) + timedelta(hours=1)
        credentials = WebexOAuthCredentials(
            access_token="access123",
            refresh_token="refresh456",
            expires_at=expires_at
        )
        
        # Save credentials
        self.client.save_credentials(credentials)
        assert self.client.credentials_file.exists()
        
        # Load credentials
        loaded = self.client.load_credentials()
        assert loaded is not None
        assert loaded.access_token == credentials.access_token
        assert loaded.refresh_token == credentials.refresh_token
        assert loaded.expires_at == credentials.expires_at

    def test_load_credentials_missing_file(self) -> None:
        """Should return None when credentials file doesn't exist."""
        result = self.client.load_credentials()
        assert result is None

    def test_load_credentials_invalid_json(self) -> None:
        """Should return None for invalid JSON."""
        # Write invalid JSON
        with open(self.client.credentials_file, 'w') as f:
            f.write("invalid json")
        
        result = self.client.load_credentials()
        assert result is None

    def test_revoke_credentials(self) -> None:
        """Should remove credentials file."""
        # Create credentials file
        credentials = WebexOAuthCredentials(
            access_token="access",
            refresh_token="refresh",
            expires_at=datetime.now(UTC) + timedelta(hours=1)
        )
        self.client.save_credentials(credentials)
        assert self.client.credentials_file.exists()
        
        # Revoke credentials
        self.client.revoke_credentials()
        assert not self.client.credentials_file.exists()

    @patch('webbrowser.open')
    @patch('summarizer.webex.oauth.OAuthCallbackServer')
    def test_start_interactive_auth_success(self, mock_server_class: MagicMock, mock_browser: MagicMock) -> None:
        """Should handle interactive authentication flow with callback server."""
        # Mock callback server
        mock_server = MagicMock()
        mock_server.start.return_value = "http://localhost:8080/callback"
        mock_server.wait_for_callback.return_value = {"code": "auth_code_123"}
        mock_server_class.return_value = mock_server
        
        # Mock the exchange_code_for_tokens method
        expected_credentials = WebexOAuthCredentials(
            access_token="access123",
            refresh_token="refresh456",
            expires_at=datetime.now(UTC) + timedelta(hours=1)
        )
        
        with patch.object(self.client, 'exchange_code_for_tokens', return_value=expected_credentials):
            credentials = self.client.start_interactive_auth()
            
            assert credentials == expected_credentials
            mock_browser.assert_called_once()
            mock_server.start.assert_called_once()
            mock_server.wait_for_callback.assert_called_once_with(timeout=300)
            mock_server.stop.assert_called()

    @patch('summarizer.webex.oauth.OAuthCallbackServer')
    def test_start_interactive_auth_timeout(self, mock_server_class: MagicMock) -> None:
        """Should raise error when callback times out."""
        # Mock callback server that times out
        mock_server = MagicMock()
        mock_server.start.return_value = "http://localhost:8080/callback"
        mock_server.wait_for_callback.side_effect = TimeoutError("OAuth callback timeout after 300 seconds")
        mock_server_class.return_value = mock_server
        
        with pytest.raises(RuntimeError, match="Authentication timeout"):
            self.client.start_interactive_auth()

    @responses.activate
    def test_get_valid_access_token_not_expired(self) -> None:
        """Should return existing token if not expired."""
        # Create non-expired credentials
        credentials = WebexOAuthCredentials(
            access_token="valid_token",
            refresh_token="refresh456",
            expires_at=datetime.now(UTC) + timedelta(hours=1)
        )
        self.client.save_credentials(credentials)
        
        token = self.client.get_valid_access_token()
        assert token == "valid_token"

    @responses.activate
    def test_get_valid_access_token_expired_refresh_success(self) -> None:
        """Should refresh expired token and return new one."""
        # Create expired credentials
        expired_credentials = WebexOAuthCredentials(
            access_token="expired_token",
            refresh_token="refresh456",
            expires_at=datetime.now(UTC) - timedelta(hours=1)
        )
        self.client.save_credentials(expired_credentials)
        
        # Mock successful refresh
        refresh_response = {
            "access_token": "new_token",
            "expires_in": 1209600
        }
        responses.add(
            responses.POST,
            "https://webexapis.com/v1/access_token", 
            json=refresh_response,
            status=200
        )
        
        token = self.client.get_valid_access_token()
        assert token == "new_token"

    def test_get_valid_access_token_no_credentials(self) -> None:
        """Should return None when no credentials exist."""
        token = self.client.get_valid_access_token()
        assert token is None