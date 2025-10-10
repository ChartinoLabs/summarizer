"""Abstract base classes for platform runners."""

import logging
from abc import ABC, abstractmethod
from datetime import UTC, datetime, timedelta, tzinfo
from typing import TYPE_CHECKING

from summarizer.common.config import BaseConfig
from summarizer.common.console_ui import (
    console,
    display_conversations,
    display_conversations_summary,
)
from summarizer.common.grouping import group_all_conversations
from summarizer.common.models import Message

if TYPE_CHECKING:
    from summarizer.common.models import Conversation

logger = logging.getLogger(__name__)


class BaseRunner(ABC):
    """Abstract base class for platform-specific runners."""

    def __init__(self, config: BaseConfig) -> None:
        """Initialize with configuration."""
        self.config = config

    @abstractmethod
    def get_activity(self, date: datetime, local_tz: tzinfo) -> list[Message]:
        """Get all activity for the specified date as a list of Message objects."""
        pass

    @abstractmethod
    def get_user_id(self) -> str:
        """Get the authenticated user's ID."""
        pass

    @abstractmethod
    def connect(self) -> None:
        """Connect to the platform API and authenticate."""
        pass

    def run(self, date_header: bool = False) -> None:
        """Run the application with the given configuration."""
        local_tz = datetime.now().astimezone().tzinfo
        if local_tz is None:
            console.print(
                "[yellow]Unable to identify local timezone. Defaulting to UTC.[/]"
            )
            local_tz = UTC

        logger.info("Local timezone is %s", local_tz)

        if date_header:
            from summarizer.common.console_ui import print_date_header

            print_date_header(self.config.target_date)

        with console.status("[bold green]Connecting to APIs...[/]"):
            self.connect()

        console.print(
            f"Looking for activity on [bold]{self.config.target_date.date()}[/]..."
        )

        message_data = self.get_activity(self.config.target_date, local_tz)

        # Conversation grouping integration
        context_window = timedelta(minutes=self.config.context_window_minutes)
        user_id = self.get_user_id()
        conversations = self._group_conversations(message_data, context_window, user_id)

        # Display results
        display_conversations(
            conversations, time_display_format=self.config.time_display_format
        )
        display_conversations_summary(
            conversations, time_display_format=self.config.time_display_format
        )

    def _group_conversations(
        self,
        messages: list[Message],
        context_window: timedelta,
        user_id: str,
    ) -> list["Conversation"]:
        """Group messages into conversations using the common grouping logic."""
        # This is a platform-agnostic wrapper around the grouping functionality
        # Subclasses can override this if they need platform-specific grouping logic
        return group_all_conversations(
            messages,
            context_window,
            user_id,
            include_passive=self.config.passive_participation,
            client=None,  # Platform-specific runners should override if needed
        )
