"""Webex-specific runner implementation."""

import logging
from datetime import datetime, timedelta, tzinfo

from webexpythonsdk.exceptions import ApiError

from summarizer.common.console_ui import console
from summarizer.common.grouping import group_all_conversations
from summarizer.common.models import Conversation, Message
from summarizer.common.runner import BaseRunner
from summarizer.webex.client import WebexClient
from summarizer.webex.config import WebexConfig

logger = logging.getLogger(__name__)


class WebexRunner(BaseRunner):
    """Webex-specific runner implementation."""

    def __init__(self, config: WebexConfig) -> None:
        """Initialize with Webex configuration."""
        super().__init__(config)
        self.config: WebexConfig = config  # Type hint for better IDE support
        self.client: WebexClient | None = None

    def connect(self) -> None:
        """Connect to the Webex API and authenticate."""
        self.client = WebexClient(self.config)
        try:
            me = self.client.get_me()
        except ApiError as e:
            if "401" in str(e):
                console.print(
                    "\n[bold red]Error: The provided Webex API token is invalid.[/]"
                )
                console.print(
                    "[yellow]This may be because your token has expired or was copied "
                    "incorrectly from the Webex website.[/]"
                )
                console.print(
                    "[yellow]Please visit "
                    "[link=https://developer.webex.com/docs/getting-started]"
                    "https://developer.webex.com/docs/getting-started[/link] "
                    "to obtain a new token and try again.[/]"
                )
                logger.error("Invalid Webex API token caused API error: %s", e)
                raise
            else:
                logger.error(
                    "Webex API error when getting authenticated user information: %s", e
                )
                raise
        console.log(f"Connected as [bold green]{me.display_name}[/]")
        logger.info("Successfully connected to Webex API as %s", me.display_name)

    def get_activity(self, date: datetime, local_tz: tzinfo) -> list[Message]:
        """Get all activity for the specified date as a list of Message objects."""
        if not self.client:
            raise RuntimeError("Must call connect() before get_activity()")

        return self.client.get_activity(date, local_tz, self.config.room_chunk_size)

    def get_user_id(self) -> str:
        """Get the authenticated user's ID."""
        if not self.client:
            raise RuntimeError("Must call connect() before get_user_id()")

        return self.client.get_me().id

    def _group_conversations(
        self,
        messages: list[Message],
        context_window: timedelta,
        user_id: str,
    ) -> list[Conversation]:
        """Group messages into conversations using Webex-specific logic."""
        if not self.client:
            raise RuntimeError("Must call connect() before _group_conversations()")

        return group_all_conversations(
            messages,
            context_window,
            user_id,
            include_passive=self.config.passive_participation,
            client=self.client.client,  # Pass the underlying WebexAPI client
        )
