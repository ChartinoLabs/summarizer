"""CLI definition for the application."""

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Annotated

import typer
from dotenv import load_dotenv

from summarizer.common.logging import setup_logging
from summarizer.webex.config import WebexConfig
from summarizer.webex.runner import WebexRunner

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


#
# Date argument parsing and validation helpers
#


def _handle_date_range(start_date: str, end_date: str) -> tuple[datetime, datetime]:
    """Parse and validate the date range."""
    try:
        start_dt = datetime.strptime(start_date, "%Y-%m-%d")
        end_dt = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError as exc:
        typer.echo("[red]Invalid date format for range. Please use YYYY-MM-DD.[/red]")
        raise typer.Exit(1) from exc
    if end_dt < start_dt:
        typer.echo("[red]End date must not be before start date.[/red]")
        raise typer.Exit(1)
    return start_dt, end_dt


def _handle_single_date(target_date: str | None) -> datetime:
    """Prompt for and parse a single date if needed."""
    if target_date is None:
        current_date = datetime.now().strftime("%Y-%m-%d")
        target_date = typer.prompt(
            "Enter the date to summarize (YYYY-MM-DD)",
            default=current_date,
        )
    # This check is for safety, as prompt should handle it.
    if target_date is None:
        typer.echo("[red]No date provided.[/red]")
        raise typer.Exit(1)
    try:
        return datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError as exc:
        typer.echo("[red]Invalid date format. Please use YYYY-MM-DD.[/red]")
        raise typer.Exit(1) from exc


def _validate_and_parse_dates(
    target_date: str | None,
    start_date: str | None,
    end_date: str | None,
) -> tuple[datetime | None, datetime | None, datetime | None, str]:
    """Validate mutually exclusive date/range args and parse to datetime objects.

    Returns:
        (parsed_target_date, parsed_start_date, parsed_end_date, mode)
        mode is 'single' or 'range'.

    Raises:
        typer.Exit on error.
    """
    # Mutually exclusive validation: either a single date OR a date range
    if target_date and (start_date or end_date):
        typer.echo(
            "[red]Cannot use --target-date with --start-date or --end-date. "
            "Please choose one mode.[/red]"
        )
        raise typer.Exit(1)
    if (start_date and not end_date) or (end_date and not start_date):
        typer.echo(
            "[red]Both --start-date and --end-date must be provided for a range.[/red]"
        )
        raise typer.Exit(1)

    # Date range mode
    if start_date and end_date:
        start_dt, end_dt = _handle_date_range(start_date, end_date)
        return None, start_dt, end_dt, "range"

    # Single date mode
    parsed_date = _handle_single_date(target_date)
    return parsed_date, None, None, "single"


def _run_for_date(
    config: WebexConfig,
    date_header: bool,
) -> None:
    logger.info("Attempting to log into Webex API as user %s", config.user_email)
    logger.info("Targeted date for summarization: %s", config.target_date)
    logger.info("Context window size: %d minutes", config.context_window_minutes)
    logger.info("Passive participation: %s", config.passive_participation)
    logger.info("Time display format: %s", config.time_display_format)
    logger.info("Room fetch chunk size: %d", config.room_chunk_size)
    runner = WebexRunner(config)
    runner.run(date_header=date_header)


@app.command()
def main(
    user_email: Annotated[
        str,
        typer.Option(..., envvar="USER_EMAIL", prompt="Enter your Cisco email"),
    ],
    webex_token: Annotated[
        str,
        typer.Option(
            ...,
            envvar="WEBEX_TOKEN",
            prompt=(
                "Enter your Webex access token "
                "(https://developer.webex.com/docs/getting-started)"
            ),
            hide_input=True,
        ),
    ],
    debug: Annotated[bool, typer.Option(help="Enable debug logging")] = False,
    target_date: Annotated[
        str | None,
        typer.Option(
            help=(
                "Date in YYYY-MM-DD format "
                "(mutually exclusive with --start-date/--end-date)"
            ),
            metavar="YYYY-MM-DD",
        ),
    ] = None,
    start_date: Annotated[
        str | None,
        typer.Option(
            help=(
                "Start date for range in YYYY-MM-DD format "
                "(mutually exclusive with --target-date)"
            ),
            metavar="YYYY-MM-DD",
        ),
    ] = None,
    end_date: Annotated[
        str | None,
        typer.Option(
            help=(
                "End date for range in YYYY-MM-DD format "
                "(mutually exclusive with --target-date)"
            ),
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

    parsed_target_date, parsed_start_date, parsed_end_date, mode = (
        _validate_and_parse_dates(target_date, start_date, end_date)
    )

    if mode == "range":
        # Iterate over date range (inclusive)
        current = parsed_start_date
        if current is None or parsed_end_date is None:
            raise ValueError(
                "Both start_date and end_date must be provided for range mode"
            )
        while current <= parsed_end_date:
            config = WebexConfig(
                webex_token=webex_token,
                user_email=user_email,
                target_date=current,
                context_window_minutes=context_window_minutes,
                passive_participation=passive_participation,
                time_display_format=time_display_format.value,
                room_chunk_size=room_chunk_size,
            )
            _run_for_date(config, date_header=True)
            current += timedelta(days=1)
        return

    # Single date mode
    if parsed_target_date is None:
        raise ValueError("Target date must be provided for single date mode")
    # Construct WebexConfig for a single date
    config = WebexConfig(
        webex_token=webex_token,
        user_email=user_email,
        target_date=parsed_target_date,
        context_window_minutes=context_window_minutes,
        passive_participation=passive_participation,
        time_display_format=time_display_format.value,
        room_chunk_size=room_chunk_size,
    )
    _run_for_date(config, date_header=False)


if __name__ == "__main__":
    setup_logging()
    app()
