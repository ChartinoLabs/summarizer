"""Base configuration classes for platform-agnostic functionality."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Literal


class BaseConfig(ABC):
    """Base configuration for all platforms."""

    def __init__(
        self,
        user_email: str,
        target_date: datetime,
        context_window_minutes: int = 15,
        passive_participation: bool = False,
        time_display_format: Literal["12h", "24h"] = "12h",
    ) -> None:
        """Initialize base configuration."""
        self.user_email = user_email
        self.target_date = target_date
        self.context_window_minutes = context_window_minutes
        self.passive_participation = passive_participation
        self.time_display_format = time_display_format

    @abstractmethod
    def get_platform_name(self) -> str:
        """Return the name of the platform this config is for."""
        pass
