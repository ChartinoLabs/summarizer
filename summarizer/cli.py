"""CLI definition for the application."""

from datetime import datetime
from enum import Enum
from typing import Annotated

import typer
from dotenv import load_dotenv

from summarizer.config import AppConfig
from summarizer.runner import run_app

# Load environment variables from .env before initializing the Typer app
load_dotenv()

app = typer.Typer(pretty_exceptions_enable=False)


class TimeDisplayFormat(str, Enum):
    """Time display format."""

    h12 = "12h"
    h24 = "24h"


@app.command()
def main(
    user_email: Annotated[
        str, typer.Option(..., envvar="USER_EMAIL", prompt="Enter your Cisco email")
    ],
    webex_token: Annotated[
        str,
        typer.Option(
            ...,
            envvar="WEBEX_TOKEN",
            prompt="Enter your Webex access token (https://developer.webex.com/docs/getting-started)",
            hide_input=True,
        ),
    ],
    target_date: Annotated[
        str | None,
        typer.Option(
            help="Date in YYYY-MM-DD format",
            metavar="YYYY-MM-DD",
        ),
    ] = None,
    context_window_minutes: Annotated[
        int, typer.Option(help="Context window in minutes")
    ] = 15,
    passive_participation: Annotated[
        bool,
        typer.Option(help="Include conversations where you only received messages?"),
    ] = False,
    time_display_format: Annotated[
        TimeDisplayFormat, typer.Option(help="Time display format ('12h' or '24h')")
    ] = TimeDisplayFormat.h12,
    room_chunk_size: Annotated[int, typer.Option(help="Room fetch chunk size")] = 50,
) -> None:
    """Webex Summarizer CLI (Typer config parsing demo)."""
    # Handle target_date prompt with current date
    if target_date is None:
        current_date = datetime.now().strftime("%Y-%m-%d")
        target_date = typer.prompt(
            f"Enter the date to summarize (YYYY-MM-DD) [default: {current_date}]",
            default=current_date,
        )

    # At this point, target_date must be a string.
    if target_date is None:
        typer.echo("[red]No date provided.[/red]")
        raise typer.Exit(1)

    # Parse target_date
    try:
        parsed_date = datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError as exc:
        typer.echo("[red]Invalid date format. Please use YYYY-MM-DD.[/red]")
        raise typer.Exit(1) from exc

    # Construct AppConfig
    config = AppConfig(
        webex_token=webex_token,
        user_email=user_email,
        target_date=parsed_date,
        context_window_minutes=context_window_minutes,
        passive_participation=passive_participation,
        time_display_format=time_display_format.value,
        room_chunk_size=room_chunk_size,
    )

    run_app(config)


if __name__ == "__main__":
    app()
