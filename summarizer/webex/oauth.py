"""Webex OAuth 2.0 authentication and token management."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import secrets
import threading
import time
import urllib.parse
import webbrowser
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests
from rich.console import Console

logger = logging.getLogger(__name__)
console = Console()


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth callback."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        """Initialize handler with authorization code storage."""
        self.server_instance = None
        super().__init__(*args, **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        """Handle GET request for OAuth callback."""
        url_parts = urlparse(self.path)
        query_params = parse_qs(url_parts.query)

        # Extract authorization code
        auth_code = None
        error = None

        if "code" in query_params:
            auth_code = query_params["code"][0]
        elif "error" in query_params:
            error = query_params["error"][0]
            error_description = query_params.get(
                "error_description", ["Unknown error"]
            )[0]

        # Store the result in the server instance
        if hasattr(self.server, "oauth_result"):
            if auth_code:
                self.server.oauth_result = {"code": auth_code}
            elif error:
                self.server.oauth_result = {
                    "error": error,
                    "description": error_description,
                }

        # Send response to browser
        if auth_code:
            response_html = """
            <!DOCTYPE html>
            <html>
            <head><title>Authorization Successful</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center;
                         padding: 50px;">
                <h1 style="color: green;">✅ Authorization Successful!</h1>
                <p>You have successfully authorized the Webex integration.</p>
                <p>You can now close this browser window and return to the terminal.</p>
            </body>
            </html>
            """
            self.send_response(200)
        else:
            response_html = f"""
            <!DOCTYPE html>
            <html>
            <head><title>Authorization Failed</title></head>
            <body style="font-family: Arial, sans-serif; text-align: center;
                         padding: 50px;">
                <h1 style="color: red;">❌ Authorization Failed</h1>
                <p>Error: {error}</p>
                <p>Description: {error_description if error else "Unknown error"}</p>
                <p>Please close this window and try again.</p>
            </body>
            </html>
            """
            self.send_response(400)

        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(response_html.encode("utf-8"))

    def log_message(self, format: str, *args: Any) -> None:  # noqa: ANN401
        """Suppress default HTTP server logging."""
        pass


class OAuthCallbackServer:
    """Temporary HTTP server for handling OAuth callbacks."""

    def __init__(self, host: str = "localhost", port: int = 8080) -> None:
        """Initialize callback server."""
        self.host = host
        self.port = port
        self.server: HTTPServer | None = None
        self.server_thread: threading.Thread | None = None
        self.oauth_result: dict[str, str] | None = None

    def start(self) -> str:
        """Start the callback server and return the callback URL."""
        # Find available port starting from the preferred port
        port = self.port
        while port < self.port + 10:  # Try up to 10 ports
            try:
                self.server = HTTPServer((self.host, port), OAuthCallbackHandler)
                self.server.oauth_result = None
                break
            except OSError:
                port += 1

        if not self.server:
            raise RuntimeError(
                f"Could not start callback server on ports {self.port}-{self.port + 9}"
            )

        # Start server in background thread
        self.server_thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.server_thread.start()

        callback_url = f"http://{self.host}:{port}/callback"
        logger.debug(f"OAuth callback server started at {callback_url}")
        return callback_url

    def wait_for_callback(self, timeout: int = 300) -> dict[str, str]:
        """Wait for OAuth callback with timeout (default 5 minutes)."""
        start_time = time.time()

        while time.time() - start_time < timeout:
            if (
                self.server
                and hasattr(self.server, "oauth_result")
                and self.server.oauth_result
            ):
                result = self.server.oauth_result
                self.stop()
                return result
            time.sleep(0.5)

        self.stop()
        raise TimeoutError(f"OAuth callback timeout after {timeout} seconds")

    def stop(self) -> None:
        """Stop the callback server."""
        if self.server:
            self.server.shutdown()
            self.server.server_close()
            self.server = None

        if self.server_thread:
            self.server_thread.join(timeout=1)
            self.server_thread = None


@dataclass
class WebexOAuthCredentials:
    """OAuth credentials for Webex API access."""

    access_token: str
    refresh_token: str
    expires_at: datetime
    token_type: str = "Bearer"
    scope: str = ""

    def is_expired(self, buffer_minutes: int = 5) -> bool:
        """Check if access token is expired (with optional buffer)."""
        buffer = timedelta(minutes=buffer_minutes)
        return datetime.now(UTC) >= (self.expires_at - buffer)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        data = asdict(self)
        data["expires_at"] = self.expires_at.isoformat()
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WebexOAuthCredentials:
        """Create from dictionary (deserialization)."""
        data["expires_at"] = datetime.fromisoformat(data["expires_at"])
        return cls(**data)


@dataclass
class WebexOAuthApp:
    """OAuth application configuration for Webex."""

    client_id: str
    client_secret: str
    redirect_uri: str = "http://localhost:8080/callback"
    scopes: list[str] = None

    def __post_init__(self) -> None:
        """Set default scopes if not provided."""
        if self.scopes is None:
            self.scopes = [
                "spark:messages_read",
                "spark:rooms_read",
                "spark:people_read",
            ]

    def update_redirect_uri(self, redirect_uri: str) -> None:
        """Update the redirect URI for dynamic port allocation."""
        self.redirect_uri = redirect_uri


class WebexOAuthClient:
    """Handles Webex OAuth 2.0 authentication flow and token management."""

    # Webex OAuth endpoints
    AUTHORIZE_URL = "https://webexapis.com/v1/authorize"
    TOKEN_URL = "https://webexapis.com/v1/access_token"  # nosec B105

    def __init__(self, app_config: WebexOAuthApp) -> None:
        """Initialize OAuth client with app configuration."""
        self.app_config = app_config
        self.credentials_file = self._get_credentials_path()

    def _get_credentials_path(self) -> Path:
        """Get path to credentials file in user's home directory."""
        home = Path.home()
        config_dir = home / ".config" / "summarizer"
        config_dir.mkdir(parents=True, exist_ok=True)
        return config_dir / "webex_oauth_credentials.json"

    def _generate_pkce_params(self) -> tuple[str, str]:
        """Generate PKCE code verifier and challenge for secure OAuth flow."""
        # Generate code verifier (43-128 characters)
        code_verifier = (
            base64.urlsafe_b64encode(secrets.token_bytes(32))
            .decode("utf-8")
            .rstrip("=")
        )

        # Generate code challenge (SHA256 hash of verifier)
        challenge_bytes = hashlib.sha256(code_verifier.encode("utf-8")).digest()
        code_challenge = (
            base64.urlsafe_b64encode(challenge_bytes).decode("utf-8").rstrip("=")
        )

        return code_verifier, code_challenge

    def get_authorization_url(self) -> tuple[str, str]:
        """Generate authorization URL and return with code verifier for PKCE.

        Returns:
            Tuple of (authorization_url, code_verifier)
        """
        code_verifier, code_challenge = self._generate_pkce_params()

        params = {
            "client_id": self.app_config.client_id,
            "response_type": "code",
            "redirect_uri": self.app_config.redirect_uri,
            "scope": " ".join(self.app_config.scopes),
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "state": secrets.token_urlsafe(32),  # CSRF protection
        }

        auth_url = f"{self.AUTHORIZE_URL}?{urllib.parse.urlencode(params)}"
        return auth_url, code_verifier

    def exchange_code_for_tokens(
        self, code: str, code_verifier: str
    ) -> WebexOAuthCredentials:
        """Exchange authorization code for access and refresh tokens.

        Args:
            code: Authorization code from callback
            code_verifier: PKCE code verifier from authorization request

        Returns:
            OAuth credentials with access and refresh tokens
        """
        data = {
            "grant_type": "authorization_code",
            "client_id": self.app_config.client_id,
            "client_secret": self.app_config.client_secret,
            "code": code,
            "redirect_uri": self.app_config.redirect_uri,
            "code_verifier": code_verifier,
        }

        response = requests.post(
            self.TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        response.raise_for_status()

        token_data = response.json()

        # Calculate expiration time
        expires_in = token_data.get("expires_in", 14 * 24 * 3600)  # Default 14 days
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

        credentials = WebexOAuthCredentials(
            access_token=token_data["access_token"],
            refresh_token=token_data["refresh_token"],
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
            scope=token_data.get("scope", ""),
        )

        self.save_credentials(credentials)
        return credentials

    def refresh_access_token(
        self, credentials: WebexOAuthCredentials
    ) -> WebexOAuthCredentials:
        """Refresh access token using refresh token.

        Args:
            credentials: Current credentials with refresh token

        Returns:
            New credentials with refreshed access token
        """
        data = {
            "grant_type": "refresh_token",
            "client_id": self.app_config.client_id,
            "client_secret": self.app_config.client_secret,
            "refresh_token": credentials.refresh_token,
        }

        response = requests.post(
            self.TOKEN_URL,
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=30,
        )
        response.raise_for_status()

        token_data = response.json()

        # Calculate expiration time
        expires_in = token_data.get("expires_in", 14 * 24 * 3600)  # Default 14 days
        expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)

        # Keep existing refresh token if not provided
        # (some providers don't return new one)
        new_refresh_token = token_data.get("refresh_token", credentials.refresh_token)

        new_credentials = WebexOAuthCredentials(
            access_token=token_data["access_token"],
            refresh_token=new_refresh_token,
            expires_at=expires_at,
            token_type=token_data.get("token_type", "Bearer"),
            scope=token_data.get("scope", credentials.scope),
        )

        self.save_credentials(new_credentials)
        return new_credentials

    def load_credentials(self) -> WebexOAuthCredentials | None:
        """Load OAuth credentials from file.

        Returns:
            Credentials if file exists and is valid, None otherwise
        """
        if not self.credentials_file.exists():
            return None

        try:
            with open(self.credentials_file) as f:
                data = json.load(f)
            return WebexOAuthCredentials.from_dict(data)
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning(f"Invalid credentials file: {e}")
            return None

    def save_credentials(self, credentials: WebexOAuthCredentials) -> None:
        """Save OAuth credentials to file.

        Args:
            credentials: Credentials to save
        """
        try:
            with open(self.credentials_file, "w") as f:
                json.dump(credentials.to_dict(), f, indent=2)

            # Set restrictive permissions (read/write for owner only)
            os.chmod(self.credentials_file, 0o600)
            logger.debug(f"Saved OAuth credentials to {self.credentials_file}")
        except OSError as e:
            logger.error(f"Failed to save credentials: {e}")
            raise

    def get_valid_access_token(self) -> str | None:
        """Get a valid access token, refreshing if necessary.

        Returns:
            Valid access token or None if authentication is required
        """
        credentials = self.load_credentials()
        if not credentials:
            logger.debug("No stored credentials found")
            return None

        logger.debug(
            f"Loaded credentials - expires: {credentials.expires_at}, "
            f"scopes: {credentials.scope}"
        )

        # Check if token is expired and needs refresh
        if credentials.is_expired():
            logger.debug("Token is expired, attempting refresh")
            try:
                credentials = self.refresh_access_token(credentials)
                logger.info("Refreshed Webex access token")
            except requests.RequestException as e:
                logger.error(f"Failed to refresh token: {e}")
                return None
        else:
            logger.debug("Token is still valid, no refresh needed")

        # Log token prefix for debugging (first 10 chars)
        token_prefix = (
            credentials.access_token[:10] + "..."
            if len(credentials.access_token) > 10
            else credentials.access_token
        )
        logger.debug(f"Returning access token: {token_prefix}")

        return credentials.access_token

    def revoke_credentials(self) -> None:
        """Remove stored credentials (logout)."""
        if self.credentials_file.exists():
            self.credentials_file.unlink()
            logger.info("Removed stored Webex OAuth credentials")

    def start_interactive_auth(self) -> WebexOAuthCredentials:
        """Start interactive OAuth flow with local callback server.

        Returns:
            OAuth credentials after successful authentication

        Raises:
            RuntimeError: If authentication fails or is cancelled
        """
        # Start temporary callback server
        callback_server = OAuthCallbackServer()

        try:
            callback_url = callback_server.start()

            # Update app config with actual callback URL
            original_redirect_uri = self.app_config.redirect_uri
            self.app_config.update_redirect_uri(callback_url)

            # Generate authorization URL with dynamic callback
            auth_url, code_verifier = self.get_authorization_url()

            console.print("\n🔐 Starting Webex OAuth authentication...")
            console.print(f"📡 Temporary callback server started at: {callback_url}")
            console.print("🌐 Opening browser for authorization...")
            console.print("\nIf the browser doesn't open automatically, visit:")
            console.print(f"{auth_url}")
            console.print("\n⏳ Waiting for authorization (timeout: 5 minutes)...")

            # Open browser
            webbrowser.open(auth_url)

            # Wait for callback
            try:
                result = callback_server.wait_for_callback(timeout=300)

                if "error" in result:
                    raise RuntimeError(
                        f"Authorization failed: {result['error']} - "
                        f"{result.get('description', '')}"
                    )

                if "code" not in result:
                    raise RuntimeError("No authorization code received")

                # Exchange code for tokens
                credentials = self.exchange_code_for_tokens(
                    result["code"], code_verifier
                )
                console.print("✅ Successfully authenticated with Webex!")
                console.print(f"🔑 Access token expires: {credentials.expires_at}")
                console.print("💾 Credentials saved securely")
                return credentials

            except TimeoutError as e:
                raise RuntimeError(
                    "Authentication timeout - please try again. "
                    "Make sure to complete the authorization within 5 minutes."
                ) from e

        except Exception as e:
            callback_server.stop()
            raise RuntimeError(f"Authentication failed: {e}") from e
        finally:
            # Restore original redirect URI
            self.app_config.update_redirect_uri(original_redirect_uri)
            callback_server.stop()
