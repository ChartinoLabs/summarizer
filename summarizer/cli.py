"""CLI definition for the application."""

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Annotated

import typer
from dotenv import load_dotenv

from summarizer.config import AppConfig
from summarizer.logging import setup_logging
from summarizer.runner import run_app

# Load environment variables from .env before initializing the Typer app
load_dotenv()

# Set up logging
setup_logging()
logger = logging.getLogger(__name__)

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
    debug: Annotated[bool, typer.Option(help="Enable debug logging")] = False,
    target_date: Annotated[
        str | None,
        typer.Option(
            help="Date in YYYY-MM-DD format (mutually exclusive with --start-date/--end-date)",
            metavar="YYYY-MM-DD",
        ),
    ] = None,
    start_date: Annotated[
        str | None,
        typer.Option(
            help="Start date for range in YYYY-MM-DD format (mutually exclusive with --target-date)",
            metavar="YYYY-MM-DD",
        ),
    ] = None,
    end_date: Annotated[
        str | None,
        typer.Option(
            help="End date for range in YYYY-MM-DD format (mutually exclusive with --target-date)",
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
    if debug is True:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    # Mutually exclusive validation
    # Either pick a single date OR pick a date range
    if target_date and (start_date or end_date):
        typer.echo(
            "[red]Cannot use --target-date with --start-date or --end-date. Please choose one mode.[/red]"
        )
        raise typer.Exit(1)
    if (start_date and not end_date) or (end_date and not start_date):
        typer.echo(
            "[red]Both --start-date and --end-date must be provided for a range.[/red]"
        )
        raise typer.Exit(1)

    if start_date and end_date:
        # Parse date range
        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            end_dt = datetime.strptime(end_date, "%Y-%m-%d")
        except ValueError as exc:
            typer.echo(
                "[red]Invalid date format for range. Please use YYYY-MM-DD.[/red]"
            )
            raise typer.Exit(1) from exc
        if end_dt < start_dt:
            typer.echo("[red]End date must not be before start date.[/red]")
            raise typer.Exit(1)
        # Iterate over range (inclusive)
        current = start_dt
        while current <= end_dt:
            config = AppConfig(
                webex_token=webex_token,
                user_email=user_email,
                target_date=current,
                context_window_minutes=context_window_minutes,
                passive_participation=passive_participation,
                time_display_format=time_display_format.value,
                room_chunk_size=room_chunk_size,
            )
            run_app(config, date_header=True)
            current += timedelta(days=1)
        return

    # Single date mode (default)
    if target_date is None:
        current_date = datetime.now().strftime("%Y-%m-%d")
        target_date = typer.prompt(
            "Enter the date to summarize (YYYY-MM-DD)",
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
    logger.info("Attempting to log into Webex API as user %s", user_email)
    logger.info("Targeted date for summarization: %s", target_date)
    logger.info("Context window size: %d minutes", context_window_minutes)
    logger.info("Passive participation: %s", passive_participation)
    logger.info("Time display format: %s", time_display_format.value)
    logger.info("Room fetch chunk size: %d", room_chunk_size)

    run_app(config, date_header=False)


if __name__ == "__main__":
    setup_logging()
    app()
