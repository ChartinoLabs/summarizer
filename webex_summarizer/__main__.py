"""Summarize messages sent by a user during a period of time and GitHub commits."""

import getpass
import traceback
from datetime import UTC, datetime, timedelta
from typing import Literal, cast

from dotenv import load_dotenv
from rich.prompt import Prompt

from .config import AppConfig
from .console_ui import console, display_conversations, display_welcome_panel
from .grouping import group_all_conversations
from .webex import WebexClient


def get_user_config() -> AppConfig:
    """Get user configuration through prompts."""
    load_dotenv()

    display_welcome_panel()

    user_email = Prompt.ask("Enter your Cisco email")
    console.print("Enter your Webex access token by fetching it from the link below:")
    console.print(
        "[link=https://developer.webex.com/docs/getting-started]https://developer.webex.com/docs/getting-started[/link]"
    )
    webex_token = getpass.getpass("Enter your Webex access token: ")

    date_str = Prompt.ask("Enter the date", default=datetime.now().strftime("%Y-%m-%d"))
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError as e:
        console.print(
            "[red]Invalid date format. Please enter the date in YYYY-MM-DD format.[/]"
        )
        raise ValueError("Invalid date format") from e

    context_window_minutes = Prompt.ask(
        "Enter context window in minutes", default="15", show_default=True
    )
    try:
        context_window_minutes = int(context_window_minutes)
    except ValueError:
        context_window_minutes = 15

    passive_participation = (
        Prompt.ask(
            "Include conversations where you only received messages? (y/n)",
            default="n",
            show_default=True,
        )
        .strip()
        .lower()
        == "y"
    )

    time_display_format = Prompt.ask(
        "Time display format ('12h' or '24h')",
        choices=["12h", "24h"],
        default="12h",
        show_default=True,
    )
    time_display_format = cast(Literal["12h", "24h"], time_display_format)

    room_chunk_size = Prompt.ask(
        "Room fetch chunk size (for performance tuning)",
        default="50",
        show_default=True,
    )
    try:
        room_chunk_size = int(room_chunk_size)
    except ValueError:
        room_chunk_size = 50

    return AppConfig(
        webex_token=webex_token,
        user_email=user_email,
        target_date=date,
        context_window_minutes=context_window_minutes,
        passive_participation=passive_participation,
        time_display_format=time_display_format,
        room_chunk_size=room_chunk_size,
    )


def run_app(config: AppConfig) -> None:
    """Run the application with the given configuration."""
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is None:
        console.print(
            "[yellow]Unable to identify local timezone. Defaulting to UTC.[/]"
        )
        local_tz = UTC

    with console.status("[bold green]Connecting to APIs...[/]"):
        webex_client = WebexClient(config)

        me = webex_client.get_me()
        console.log(f"Connected as [bold green]{me.display_name}[/]")

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

    # Old message display (can be removed or replaced later)
    # display_results(message_data, me.display_name, str(config.target_date.date()))


def main() -> None:
    """Entry point for the application."""
    try:
        config = get_user_config()
        run_app(config)
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user.[/]")
    except Exception as e:
        console.print(f"[bold red]Error: {str(e)}[/]")
        console.print("[bold red]Traceback:[/]")
        console.print(traceback.format_exc())


if __name__ == "__main__":
    main()
