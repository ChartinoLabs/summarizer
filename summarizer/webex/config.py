"""Webex-specific configuration."""

from datetime import datetime
from typing import Literal

from summarizer.common.config import BaseConfig
from summarizer.webex.oauth import WebexOAuthApp, WebexOAuthClient


class WebexConfig(BaseConfig):
    """Webex-specific configuration supporting both manual tokens and OAuth."""

    def __init__(
        self,
        user_email: str,
        target_date: datetime,
        webex_token: str | None = None,
        oauth_client_id: str | None = None,
        oauth_client_secret: str | None = None,
        oauth_redirect_uri: str = "http://localhost:8080/callback",
        context_window_minutes: int = 15,
        passive_participation: bool = False,
        time_display_format: Literal["12h", "24h"] = "12h",
        room_chunk_size: int = 50,
    ) -> None:
        """Initialize Webex configuration.
        
        Args:
            user_email: Webex user email address
            target_date: Date to analyze activity for
            webex_token: Manual access token (legacy, optional)
            oauth_client_id: OAuth application client ID (optional)
            oauth_client_secret: OAuth application client secret (optional)  
            oauth_redirect_uri: OAuth redirect URI for authorization flow
            context_window_minutes: Window for message context
            passive_participation: Include passive participation
            time_display_format: Time format preference
            room_chunk_size: Batch size for room processing
        """
        super().__init__(
            user_email=user_email,
            target_date=target_date,
            context_window_minutes=context_window_minutes,
            passive_participation=passive_participation,
            time_display_format=time_display_format,
        )
        self.webex_token = webex_token
        self.oauth_client_id = oauth_client_id
        self.oauth_client_secret = oauth_client_secret
        self.oauth_redirect_uri = oauth_redirect_uri
        self.room_chunk_size = room_chunk_size
        
        # Initialize OAuth client if credentials provided
        self._oauth_client: WebexOAuthClient | None = None
        if oauth_client_id and oauth_client_secret:
            app_config = WebexOAuthApp(
                client_id=oauth_client_id,
                client_secret=oauth_client_secret,
                redirect_uri=oauth_redirect_uri
            )
            self._oauth_client = WebexOAuthClient(app_config)

    def get_platform_name(self) -> str:
        """Return the name of the platform this config is for."""
        return "webex"
    
    def is_active(self) -> bool:
        """Check if Webex is configured and active."""
        return bool(self.user_email and (self.webex_token or self._oauth_client))
    
    def has_oauth_config(self) -> bool:
        """Check if OAuth configuration is available."""
        return self._oauth_client is not None
    
    def get_oauth_client(self) -> WebexOAuthClient | None:
        """Get OAuth client if configured."""
        return self._oauth_client
    
    def get_access_token(self) -> str | None:
        """Get a valid access token from either manual token or OAuth.
        
        Returns:
            Valid access token or None if no authentication available
        """
        import logging
        logger = logging.getLogger(__name__)
        
        # Try OAuth first (preferred method)
        if self._oauth_client:
            logger.debug("Attempting to get OAuth access token")
            try:
                token = self._oauth_client.get_valid_access_token()
                if token:
                    logger.debug("Successfully obtained OAuth access token")
                    return token
                else:
                    logger.debug("OAuth client returned None - no valid token available")
            except Exception as e:
                logger.debug(f"OAuth token retrieval failed: {e}")
        
        # Fall back to manual token
        if self.webex_token:
            logger.debug("Using manual Webex token")
            return self.webex_token
        
        logger.debug("No access token available")
        return None
