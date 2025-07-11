"""Configuration handling for webex-summarizer."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from dotenv import load_dotenv


@dataclass
class AppConfig:
    """Application configuration."""

    webex_token: str
    user_email: str
    target_date: datetime
    context_window_minutes: int = 15
    passive_participation: bool = False
    time_display_format: Literal["12h", "24h"] = "12h"
    room_chunk_size: int = 50


def load_config_from_env() -> None:
    """Load configuration from environment variables."""
    load_dotenv()
