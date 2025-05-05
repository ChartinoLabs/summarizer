"""Configuration handling for webex-summarizer."""

from dataclasses import dataclass
from datetime import datetime

from dotenv import load_dotenv


@dataclass
class AppConfig:
    """Application configuration."""

    webex_token: str
    user_email: str
    target_date: datetime
    organizations_to_ignore: list[str] | None = None


def load_config_from_env() -> None:
    """Load configuration from environment variables."""
    load_dotenv()
