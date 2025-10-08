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

    def get_activity(
        self, date: datetime, local_tz: tzinfo, all_messages: bool = False
    ) -> list[Message]:
        """Get all activity for the specified date as a list of Message objects."""
        if not self.client:
            raise RuntimeError("Must call connect() before get_activity()")

        return self.client.get_activity(
            date, local_tz, self.config.room_chunk_size, all_messages
        )

    def get_room_messages(
        self,
        room_search_mode: str,
        room_search_value: str,
        local_tz: tzinfo,
        apply_date_filter: bool = True,
    ) -> list[Message] | None:
        """Get messages from a specific room.

        Args:
            room_search_mode: Type of room search (room_id, room_name, person_name)
            room_search_value: Value to search for
            local_tz: Local timezone
            apply_date_filter: Whether to filter messages by target date

        Returns:
            List of messages or None if room not found
        """
        if not self.client:
            raise RuntimeError("Must call connect() before get_room_messages()")

        # Find the room
        room = self._find_room_by_search_mode(room_search_mode, room_search_value)

        if room is None:
            console.print(f"[red]Could not find room/person: {room_search_value}[/]")
            self._display_room_not_found_help(room_search_mode)
            return None

        console.print(f"Found room: [bold green]{room.title}[/] (ID: {room.id})")

        # Get all messages from the room
        message_data = self.client.get_all_messages_from_room(
            room, self.config.max_messages, local_tz
        )

        # Apply date filtering if specified
        if apply_date_filter and self.config.target_date:
            original_count = len(message_data)
            message_data = [
                msg
                for msg in message_data
                if msg.timestamp.date() == self.config.target_date.date()
            ]
            console.print(
                f"Filtered to [bold]{len(message_data)}[/] messages from "
                f"[bold]{self.config.target_date.date()}[/] (out of {original_count} total)"
            )
        return message_data

    def _find_room_by_search_mode(
        self, room_search_mode: str, room_search_value: str
    ) -> object | None:
        """Find a room based on search mode and value."""
        if not self.client:
            raise RuntimeError("Must call connect() before _find_room_by_search_mode()")

        if room_search_mode == "room_id":
            console.print(f"Looking for room with ID [bold]{room_search_value}[/]...")
            return self.client.find_room_by_id(room_search_value)
        elif room_search_mode == "room_name":
            console.print(f"Looking for room named [bold]{room_search_value}[/]...")
            return self.client.find_room_by_name(room_search_value)
        elif room_search_mode == "person_name":
            console.print(f"Looking for DM with [bold]{room_search_value}[/]...")
            return self.client.find_dm_room_by_person_name(room_search_value)
        return None

    def _display_room_not_found_help(self, room_search_mode: str) -> None:
        """Display helpful error messages when room is not found."""
        if room_search_mode == "room_id":
            console.print(
                "[yellow]Please verify the room ID is correct and you have access to it.[/]"
            )
        elif room_search_mode == "room_name":
            console.print(
                "[yellow]Please verify the room name is exactly "
                "correct (case-sensitive).[/]"
            )
        elif room_search_mode == "person_name":
            console.print(
                "[yellow]Please verify the person's name is exactly "
                "correct and you have a DM with them.[/]"
            )

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
            all_messages=self.config.all_messages,
        )

    def run(
        self,
        date_header: bool = False,
        room_search_mode: str | None = None,
        room_search_value: str | None = None,
        apply_date_filter: bool = True,
    ) -> None:
        """Run the Webex application with optional room search support."""
        local_tz = datetime.now().astimezone().tzinfo
        if local_tz is None:
            console.print(
                "[yellow]Unable to identify local timezone. Defaulting to UTC.[/]"
            )
            from datetime import UTC

            local_tz = UTC

        logger.info("Local timezone is %s", local_tz)

        if date_header and self.config.target_date:
            from summarizer.common.console_ui import print_date_header

            print_date_header(self.config.target_date)

        with console.status("[bold green]Connecting to APIs...[/]"):
            self.connect()

        # Get message data based on search mode
        if room_search_mode and room_search_value:
            # Room-specific workflow
            message_data = self.get_room_messages(
                room_search_mode,
                room_search_value,
                local_tz,
                apply_date_filter,
            )
            if message_data is None:
                return
        else:
            # Traditional date-based workflow
            if self.config.target_date is None:
                raise ValueError(
                    "Target date is required for traditional date-based workflow"
                )
            console.print(
                f"Looking for activity on [bold]{self.config.target_date.date()}[/]..."
            )
            message_data = self.get_activity(
                self.config.target_date, local_tz, self.config.all_messages
            )

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
