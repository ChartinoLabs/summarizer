"""Contains core orchestration logic for the application."""

import logging
from datetime import UTC, datetime, timedelta

from webexpythonsdk.exceptions import ApiError

from summarizer.config import AppConfig
from summarizer.console_ui import (
    console,
    display_conversations,
    display_conversations_summary,
)
from summarizer.grouping import group_all_conversations
from summarizer.webex import WebexClient

logger = logging.getLogger(__name__)


def run_app(
    config: AppConfig, 
    date_header: bool = False,
    room_search_mode: str | None = None,
    room_search_value: str | None = None,
    apply_date_filter: bool = True,
) -> None:
    """Run the application with the given configuration.

    Optionally print a date header. Can operate in room-specific mode.
    
    Args:
        config: Application configuration
        date_header: Whether to print a date header
        room_search_mode: Type of room search ('room_id', 'room_name', 'person_name')
        room_search_value: Value to search for
        apply_date_filter: Whether to filter messages by date (False for room-only searches)
    """
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is None:
        console.print(
            "[yellow]Unable to identify local timezone. Defaulting to UTC.[/]"
        )
        local_tz = UTC

    logger.info("Local timezone is %s", local_tz)

    if date_header:
        from summarizer.console_ui import print_date_header

        print_date_header(config.target_date)

    with console.status("[bold green]Connecting to APIs...[/]"):
        webex_client = WebexClient(config)
        try:
            me = webex_client.get_me()
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
                return
            else:
                logger.error(
                    "Webex API error when getting authenticated user information: %s", e
                )
                raise
        console.log(f"Connected as [bold green]{me.display_name}[/]")
        logger.info("Successfully connected to Webex API as %s", me.display_name)

    # Handle room-specific or date-based workflow
    if room_search_mode and room_search_value:
        # Room-specific workflow
        room = None
        if room_search_mode == "room_id":
            console.print(f"Looking for room with ID [bold]{room_search_value}[/]...")
            room = webex_client.find_room_by_id(room_search_value)
        elif room_search_mode == "room_name":
            console.print(f"Looking for room named [bold]{room_search_value}[/]...")
            room = webex_client.find_room_by_name(room_search_value)
        elif room_search_mode == "person_name":
            console.print(f"Looking for DM with [bold]{room_search_value}[/]...")
            room = webex_client.find_dm_room_by_person_name(room_search_value)

        if room is None:
            console.print(f"[red]Could not find room/person: {room_search_value}[/]")
            if room_search_mode == "room_id":
                console.print("[yellow]Please verify the room ID is correct and you have access to it.[/]")
            elif room_search_mode == "room_name":
                console.print("[yellow]Please verify the room name is exactly correct (case-sensitive).[/]")
            elif room_search_mode == "person_name":
                console.print("[yellow]Please verify the person's name is exactly correct and you have a DM with them.[/]")
            return

        console.print(f"Found room: [bold green]{room.title}[/] (ID: {room.id})")
        
        # Get all messages from the room
        message_data = webex_client.get_all_messages_from_room(
            room, config.max_messages, local_tz
        )
        
        # Apply date filtering if specified
        # Note: For room-specific searches with date ranges, we still filter here
        # since we retrieved all messages from the room first
        # This is different from the traditional workflow which pre-filters by date
        if apply_date_filter and config.target_date:
            original_count = len(message_data)
            message_data = [
                msg for msg in message_data 
                if msg.timestamp.date() == config.target_date.date()
            ]
            console.print(
                f"Filtered to [bold]{len(message_data)}[/] messages from "
                f"[bold]{config.target_date.date()}[/] (out of {original_count} total)"
            )
    else:
        # Traditional date-based workflow
        if config.target_date is None:
            raise ValueError("Target date is required for traditional date-based workflow")
        console.print(f"Looking for activity on [bold]{config.target_date.date()}[/]...")
        message_data = webex_client.get_activity(
            config.target_date, local_tz, config.room_chunk_size
        )

    # Conversation grouping integration
    context_window = timedelta(minutes=config.context_window_minutes)
    user_id = me.id
    conversations = group_all_conversations(
        message_data,
        context_window,
        user_id,
        include_passive=config.passive_participation,
        client=webex_client.client,
    )

    # Improved conversation reporting
    display_conversations(conversations, time_display_format=config.time_display_format)

    # Display conversation summary table
    display_conversations_summary(
        conversations, time_display_format=config.time_display_format
    )
