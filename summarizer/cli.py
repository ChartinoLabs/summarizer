"""CLI definition for the application."""

import logging
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Annotated

import typer
from dotenv import load_dotenv

from summarizer.config import AppConfig
from summarizer.console_ui import console
from summarizer.logging import setup_logging
from summarizer.runner import run_app
from summarizer.webex import WebexClient
from summarizer.yaml_utils import load_users_from_yaml

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


def _validate_room_parameters(
    room_id: str | None,
    room_name: str | None,
    person_name: str | None,
) -> str | None:
    """Validate room-specific parameters and return the search mode.

    Returns:
        Search mode: 'room_id', 'room_name', 'person_name', or None if no room params.

    Raises:
        typer.Exit on validation error.
    """
    room_params = [room_id, room_name, person_name]
    active_params = [p for p in room_params if p is not None]

    if len(active_params) > 1:
        typer.echo(
            "[red]Cannot use multiple room identification options simultaneously. "
            "Please choose only one of --room-id, --room-name, or --person-name.[/red]"
        )
        raise typer.Exit(1)

    if room_id:
        return "room_id"
    elif room_name:
        return "room_name"
    elif person_name:
        return "person_name"
    else:
        return None


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


def _handle_room_search_dates(
    room_search_mode: str | None,
    target_date: str | None,
    start_date: str | None,
    end_date: str | None,
) -> tuple[datetime | None, datetime | None, datetime | None, str | None]:
    """Handle date parsing for room-based searches.

    Returns:
        (parsed_target_date, parsed_start_date, parsed_end_date, date_mode)
    """
    if room_search_mode:
        # Room-based search - dates are optional for filtering
        if target_date or start_date or end_date:
            return _validate_and_parse_dates(target_date, start_date, end_date)
        else:
            # No date filtering - retrieve all messages from room
            return None, None, None, None
    else:
        # Traditional date-based search - validate dates
        parsed_target_date, parsed_start_date, parsed_end_date, date_mode = (
            _validate_and_parse_dates(target_date, start_date, end_date)
        )

        # If no explicit date provided, prompt for one
        if date_mode == "single" and target_date is None:
            parsed_target_date = _handle_single_date(None)
            date_mode = "single"
        elif parsed_target_date is None and parsed_start_date is None:
            typer.echo(
                "[red]Please specify either date-based options (--target-date, "
                "--start-date/--end-date) or room-based options (--room-id, "
                "--room-name, --person-name).[/red]"
            )
            raise typer.Exit(1)

        return parsed_target_date, parsed_start_date, parsed_end_date, date_mode


def _run_date_range(
    parsed_start_date: datetime,
    parsed_end_date: datetime,
    webex_token: str,
    user_email: str,
    context_window_minutes: int,
    passive_participation: bool,
    time_display_format: str,
    room_chunk_size: int,
    max_messages: int,
    room_search_mode: str | None,
    room_search_value: str | None,
    all_messages: bool,
) -> None:
    """Execute date range workflow."""
    current = parsed_start_date
    while current <= parsed_end_date:
        config = AppConfig(
            webex_token=webex_token,
            user_email=user_email,
            target_date=current,
            context_window_minutes=context_window_minutes,
            passive_participation=passive_participation,
            time_display_format=time_display_format,
            room_chunk_size=room_chunk_size,
            max_messages=max_messages,
            all_messages=all_messages,
        )
        _run_for_date(
            config,
            date_header=True,
            room_search_mode=room_search_mode,
            room_search_value=room_search_value,
            apply_date_filter=True,
        )
        current += timedelta(days=1)


def _run_for_date(
    config: AppConfig,
    date_header: bool,
    room_search_mode: str | None = None,
    room_search_value: str | None = None,
    apply_date_filter: bool = True,
) -> None:
    logger.info("Attempting to log into Webex API as user %s", config.user_email)
    if room_search_mode:
        logger.info(
            "Room search mode: %s with value: %s",
            room_search_mode,
            room_search_value,
        )
        logger.info("Max messages to retrieve: %d", config.max_messages)
    else:
        logger.info("Targeted date for summarization: %s", config.target_date)
    logger.info("Context window size: %d minutes", config.context_window_minutes)
    logger.info("Passive participation: %s", config.passive_participation)
    logger.info("Time display format: %s", config.time_display_format)
    logger.info("Room fetch chunk size: %d", config.room_chunk_size)
    run_app(
        config,
        date_header=date_header,
        room_search_mode=room_search_mode,
        room_search_value=room_search_value,
        apply_date_filter=apply_date_filter,
    )


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
    room_id: Annotated[
        str | None,
        typer.Option(
            help="Specific room ID to retrieve all messages from (exact match)"
        ),
    ] = None,
    room_name: Annotated[
        str | None,
        typer.Option(
            help="Specific room name to retrieve all messages from (exact match)"
        ),
    ] = None,
    person_name: Annotated[
        str | None,
        typer.Option(help="Person name to find DM room with (exact match)"),
    ] = None,
    max_messages: Annotated[
        int, typer.Option(help="Maximum number of messages to retrieve from room")
    ] = 1000,
    all_messages: Annotated[
        bool,
        typer.Option(
            help="Retrieve ALL messages from room regardless of user participation"
        ),
    ] = False,
) -> None:
    """Webex Summarizer CLI (Typer config parsing demo)."""
    if debug is True:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    # Validate room parameters and get search mode
    room_search_mode = _validate_room_parameters(room_id, room_name, person_name)
    room_search_value = room_id or room_name or person_name

    # Handle date parameters based on whether room search is specified
    parsed_target_date, parsed_start_date, parsed_end_date, date_mode = (
        _handle_room_search_dates(room_search_mode, target_date, start_date, end_date)
    )

    # Handle date range mode
    if date_mode == "range":
        if parsed_start_date is None or parsed_end_date is None:
            raise ValueError(
                "Both start_date and end_date must be provided for range mode"
            )
        _run_date_range(
            parsed_start_date,
            parsed_end_date,
            webex_token,
            user_email,
            context_window_minutes,
            passive_participation,
            time_display_format.value,
            room_chunk_size,
            max_messages,
            room_search_mode,
            room_search_value,
            all_messages,
        )
        return

    # Single date mode or room-only mode
    if parsed_target_date is None and not room_search_mode:
        raise ValueError("Target date must be provided for single date mode")

    # Construct AppConfig and run
    config = AppConfig(
        webex_token=webex_token,
        user_email=user_email,
        target_date=parsed_target_date,
        context_window_minutes=context_window_minutes,
        passive_participation=passive_participation,
        time_display_format=time_display_format.value,
        room_chunk_size=room_chunk_size,
        max_messages=max_messages,
        all_messages=all_messages,
    )

    # Determine if we should apply date filtering
    should_apply_date_filter = not (room_search_mode and parsed_target_date is None)

    _run_for_date(
        config,
        date_header=False,
        room_search_mode=room_search_mode,
        room_search_value=room_search_value,
        apply_date_filter=should_apply_date_filter,
    )


@app.command()
def add_users(
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
    room_id: Annotated[
        str,
        typer.Option(..., help="Room ID to add users to"),
    ],
    users_file: Annotated[
        Path,
        typer.Option(..., help="Path to YAML file containing user list"),
    ],
    debug: Annotated[bool, typer.Option(help="Enable debug logging")] = False,
) -> None:
    """Add users from a YAML file to a Webex room.

    This command reads a YAML file containing team member information (with cec_id
    fields) and adds each user to the specified Webex room. Users are added with
    email addresses in the format {cec_id}@cisco.com.

    The YAML file should follow the team structure with a 'members' list where each
    member has a 'cec_id' field.

    Example YAML structure:
        name: team-name
        members:
          - username: jsmith
            cec_id: jsmith
            full_name: John Smith

    Users who are already members of the room are counted as successful additions.
    A report of failed additions (if any) will be written to failed_additions.yaml.
    """
    if debug is True:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    # Load user emails from YAML file
    try:
        user_emails = load_users_from_yaml(users_file)
    except (FileNotFoundError, ValueError, Exception) as e:
        console.print(f"[red]Error loading users from YAML file: {e}[/red]")
        raise typer.Exit(1) from e

    if not user_emails:
        console.print("[yellow]No users found in YAML file. Exiting.[/yellow]")
        raise typer.Exit(0)

    console.print(f"[blue]Loaded {len(user_emails)} users from {users_file}[/blue]")

    # Initialize Webex client
    config = AppConfig(
        webex_token=webex_token,
        user_email="",  # Not needed for this operation
        target_date=None,
        context_window_minutes=0,
        passive_participation=False,
        time_display_format="12h",
        room_chunk_size=50,
        max_messages=1000,
        all_messages=False,
    )
    client = WebexClient(config)

    # Add users to room
    try:
        successful, failed = client.add_users_to_room(room_id, user_emails)
    except Exception as e:
        console.print(f"[red]Error adding users to room: {e}[/red]")
        raise typer.Exit(1) from e

    # Display results
    console.print(
        f"\n[bold green]Successfully added {len(successful)} users "
        f"to the room[/bold green]"
    )

    if failed:
        console.print(f"[bold yellow]Failed to add {len(failed)} users[/bold yellow]")

        # Write failed additions to a report file
        failed_report_path = Path("failed_additions.yaml")
        try:
            import yaml

            failed_data = {
                "room_id": room_id,
                "timestamp": datetime.now().isoformat(),
                "failed_users": [
                    {"email": email, "error": error} for email, error in failed
                ],
            }

            with failed_report_path.open("w") as f:
                yaml.dump(failed_data, f, default_flow_style=False)

            console.print(
                f"[yellow]Failed additions written to {failed_report_path}[/yellow]"
            )
        except Exception as e:
            logger.error("Failed to write error report: %s", e)
            console.print(
                f"[red]Warning: Could not write failed additions report: {e}[/red]"
            )

        # Also print failed users to console for immediate visibility
        console.print("\n[yellow]Failed additions:[/yellow]")
        for email, error in failed:
            console.print(f"  - {email}: {error}")
    else:
        console.print("[bold green]All users added successfully![/bold green]")


if __name__ == "__main__":
    setup_logging()
    app()
