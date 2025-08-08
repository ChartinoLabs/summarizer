"""Webex-specific configuration."""

from datetime import datetime
from typing import Literal

from summarizer.common.config import BaseConfig


class WebexConfig(BaseConfig):
    """Webex-specific configuration."""

    def __init__(
        self,
        webex_token: str,
        user_email: str,
        target_date: datetime,
        context_window_minutes: int = 15,
        passive_participation: bool = False,
        time_display_format: Literal["12h", "24h"] = "12h",
        room_chunk_size: int = 50,
    ) -> None:
        """Initialize Webex configuration."""
        super().__init__(
            user_email=user_email,
            target_date=target_date,
            context_window_minutes=context_window_minutes,
            passive_participation=passive_participation,
            time_display_format=time_display_format,
        )
        self.webex_token = webex_token
        self.room_chunk_size = room_chunk_size

    def get_platform_name(self) -> str:
        """Return the name of the platform this config is for."""
        return "webex"
