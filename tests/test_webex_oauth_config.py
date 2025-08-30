"""Tests for WebexConfig OAuth integration."""

from datetime import datetime
from unittest.mock import MagicMock, patch

from summarizer.webex.config import WebexConfig


class TestWebexConfigOAuth:
    """Test cases for WebexConfig OAuth functionality."""

    def test_config_with_manual_token_only(self) -> None:
        """Should work with manual token only (legacy mode)."""
        config = WebexConfig(
            user_email="test@example.com",
            target_date=datetime(2024, 1, 1),
            webex_token="manual_token_123"
        )
        
        assert config.webex_token == "manual_token_123"
        assert config.oauth_client_id is None
        assert config.oauth_client_secret is None
        assert not config.has_oauth_config()
        assert config.get_oauth_client() is None
        assert config.is_active()  # Should be active with manual token

    def test_config_with_oauth_credentials(self) -> None:
        """Should initialize OAuth client with provided credentials."""
        config = WebexConfig(
            user_email="test@example.com",
            target_date=datetime(2024, 1, 1),
            oauth_client_id="client123",
            oauth_client_secret="secret456"
        )
        
        assert config.oauth_client_id == "client123"
        assert config.oauth_client_secret == "secret456"
        assert config.has_oauth_config()
        assert config.get_oauth_client() is not None
        assert config.is_active()  # Should be active with OAuth config

    def test_config_with_both_token_and_oauth(self) -> None:
        """Should support both manual token and OAuth credentials."""
        config = WebexConfig(
            user_email="test@example.com", 
            target_date=datetime(2024, 1, 1),
            webex_token="manual_token",
            oauth_client_id="client123",
            oauth_client_secret="secret456"
        )
        
        assert config.webex_token == "manual_token"
        assert config.has_oauth_config()
        assert config.is_active()

    def test_config_without_credentials(self) -> None:
        """Should not be active without any credentials."""
        config = WebexConfig(
            user_email="test@example.com",
            target_date=datetime(2024, 1, 1)
        )
        
        assert not config.has_oauth_config()
        assert config.get_oauth_client() is None
        assert not config.is_active()  # No auth credentials

    def test_config_without_user_email(self) -> None:
        """Should not be active without user email even with credentials."""
        config = WebexConfig(
            user_email="",  # Empty email
            target_date=datetime(2024, 1, 1),
            webex_token="token123"
        )
        
        assert not config.is_active()  # No user email

    @patch('summarizer.webex.config.WebexOAuthClient')
    def test_get_access_token_oauth_preferred(self, mock_oauth_client_class: MagicMock) -> None:
        """Should prefer OAuth token over manual token."""
        # Mock OAuth client to return a token
        mock_oauth_client = MagicMock()
        mock_oauth_client.get_valid_access_token.return_value = "oauth_token_123"
        mock_oauth_client_class.return_value = mock_oauth_client
        
        config = WebexConfig(
            user_email="test@example.com",
            target_date=datetime(2024, 1, 1),
            webex_token="manual_token",  # Should be ignored in favor of OAuth
            oauth_client_id="client123",
            oauth_client_secret="secret456"
        )
        
        token = config.get_access_token()
        assert token == "oauth_token_123"
        mock_oauth_client.get_valid_access_token.assert_called_once()

    @patch('summarizer.webex.config.WebexOAuthClient')
    def test_get_access_token_fallback_to_manual(self, mock_oauth_client_class: MagicMock) -> None:
        """Should fallback to manual token if OAuth fails."""
        # Mock OAuth client to return None (no valid token)
        mock_oauth_client = MagicMock()
        mock_oauth_client.get_valid_access_token.return_value = None
        mock_oauth_client_class.return_value = mock_oauth_client
        
        config = WebexConfig(
            user_email="test@example.com",
            target_date=datetime(2024, 1, 1),
            webex_token="manual_token_fallback",
            oauth_client_id="client123",
            oauth_client_secret="secret456"
        )
        
        token = config.get_access_token()
        assert token == "manual_token_fallback"

    def test_get_access_token_manual_only(self) -> None:
        """Should return manual token when no OAuth configured."""
        config = WebexConfig(
            user_email="test@example.com",
            target_date=datetime(2024, 1, 1),
            webex_token="manual_only_token"
        )
        
        token = config.get_access_token()
        assert token == "manual_only_token"

    def test_get_access_token_no_credentials(self) -> None:
        """Should return None when no credentials available."""
        config = WebexConfig(
            user_email="test@example.com",
            target_date=datetime(2024, 1, 1)
        )
        
        token = config.get_access_token()
        assert token is None

    def test_oauth_redirect_uri_default(self) -> None:
        """Should use default redirect URI."""
        config = WebexConfig(
            user_email="test@example.com",
            target_date=datetime(2024, 1, 1),
            oauth_client_id="client123",
            oauth_client_secret="secret456"
        )
        
        assert config.oauth_redirect_uri == "http://localhost:8080/callback"

    def test_oauth_redirect_uri_custom(self) -> None:
        """Should use custom redirect URI when provided."""
        custom_uri = "https://myapp.com/oauth/callback"
        config = WebexConfig(
            user_email="test@example.com",
            target_date=datetime(2024, 1, 1),
            oauth_client_id="client123",
            oauth_client_secret="secret456",
            oauth_redirect_uri=custom_uri
        )
        
        assert config.oauth_redirect_uri == custom_uri

    def test_platform_name(self) -> None:
        """Should return correct platform name."""
        config = WebexConfig(
            user_email="test@example.com",
            target_date=datetime(2024, 1, 1)
        )
        
        assert config.get_platform_name() == "webex"