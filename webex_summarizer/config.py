"""Configuration handling for webex-summarizer."""

import os
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from dotenv import load_dotenv


@dataclass
class AppConfig:
    """Application configuration."""
    webex_token: str
    github_token: str
    github_base_url: str
    user_email: str
    target_date: datetime
    organizations_to_ignore: Optional[List[str]] = None

    def __post_init__(self):
        """Set default values after initialization."""
        if self.organizations_to_ignore is None:
            self.organizations_to_ignore = [
                "AS-Community",
                "besaccess",
                "cx-usps-auto",
                "SVS-DELIVERY",
                "pyATS",
                "netascode",
                "CX-CATL",
            ]

def load_config_from_env() -> dict:
    """Load configuration from environment variables."""
    load_dotenv()
    
    return {
        "github_token": os.getenv("GITHUB_PAT"),
        "github_base_url": os.getenv("GITHUB_BASE_URL"),
    }


def get_known_github_instances() -> List[str]:
    """Return list of known GitHub instances."""
    return [
        "https://github.com/api/v3",
        "https://wwwin-github.cisco.com/api/v3",
    ]
