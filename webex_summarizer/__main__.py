"""Summarize messages sent by a user during a period of time and GitHub commits."""

import getpass
from datetime import UTC, datetime

from dotenv import load_dotenv
from rich.prompt import Prompt

from .config import AppConfig
from .console_ui import console, display_results, display_welcome_panel
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

    return AppConfig(
        webex_token=webex_token,
        user_email=user_email,
        target_date=date,
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
        console.log(f"Connected as [bold green]{me.displayName}[/]")

    console.print(f"Looking for activity on [bold]{config.target_date.date()}[/]...")

    message_data = webex_client.get_activity(config.target_date, local_tz)

    display_results(message_data, me.displayName, str(config.target_date.date()))


def main() -> None:
    """Entry point for the application."""
    try:
        config = get_user_config()
        run_app(config)
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user.[/]")
    except Exception as e:
        console.print(f"[bold red]Error: {str(e)}[/]")


if __name__ == "__main__":
    main()
