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


def run_app(config: AppConfig, date_header: bool = False) -> None:
    """Run the application with the given configuration.

    Optionally print a date header.
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
    )

    # Improved conversation reporting
    display_conversations(conversations, time_display_format=config.time_display_format)

    # Display conversation summary table
    display_conversations_summary(
        conversations, time_display_format=config.time_display_format
    )
