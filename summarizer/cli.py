"""CLI definition for the application."""

import logging
from datetime import datetime, timedelta
from enum import Enum
from typing import Annotated

import typer
from dotenv import load_dotenv

from summarizer.common.logging import setup_logging
from summarizer.common.models import ChangeType
from summarizer.github.config import GithubConfig
from summarizer.github.runner import GithubRunner
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


def _run_webex_for_date(config: WebexConfig, date_header: bool) -> None:
    logger.info("Attempting to log into Webex API as user %s", config.user_email)
    logger.info("Targeted date for summarization: %s", config.target_date)
    logger.info("Context window size: %d minutes", config.context_window_minutes)
    logger.info("Passive participation: %s", config.passive_participation)
    logger.info("Time display format: %s", config.time_display_format)
    logger.info("Room fetch chunk size: %d", config.room_chunk_size)
    runner = WebexRunner(config)
    runner.run(date_header=date_header)


def _run_github_for_date(config: GithubConfig, date_header: bool) -> None:
    logger.info("Attempting to access GitHub as user %s", config.user)
    logger.info("Targeted date for summarization: %s", config.target_date)
    runner = GithubRunner(config)
    runner.run(date_header=date_header)


_INCLUDE_SYNONYMS: dict[str, ChangeType] = {
    "commit": ChangeType.COMMIT,
    "commits": ChangeType.COMMIT,
    "issue": ChangeType.ISSUE,
    "issues": ChangeType.ISSUE,
    "pr": ChangeType.PULL_REQUEST,
    "prs": ChangeType.PULL_REQUEST,
    "pull_request": ChangeType.PULL_REQUEST,
    "pull_requests": ChangeType.PULL_REQUEST,
    "issue_comment": ChangeType.ISSUE_COMMENT,
    "issue_comments": ChangeType.ISSUE_COMMENT,
    "pr_comment": ChangeType.PR_COMMENT,
    "pr_comments": ChangeType.PR_COMMENT,
    "pull_request_comment": ChangeType.PR_COMMENT,
    "pull_request_comments": ChangeType.PR_COMMENT,
    "review": ChangeType.REVIEW,
    "reviews": ChangeType.REVIEW,
}


def _parse_change_types(values: list[str] | None) -> set[ChangeType]:
    if not values:
        return set(ChangeType)
    result: set[ChangeType] = set()
    for v in values:
        key = (v or "").strip().lower()
        if not key:
            continue
        ct = _INCLUDE_SYNONYMS.get(key)
        if ct is not None:
            result.add(ct)
            continue
        try:
            result.add(ChangeType[key.upper()])
        except Exception:
            # ignore unknown values
            pass
    return result or set(ChangeType)


def _split_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    parts = [p.strip() for p in value.replace("\n", ",").split(",")]
    return [p for p in parts if p]


def _build_webex_config(
    *,
    date: datetime,
    webex_token: str | None,
    user_email: str | None,
    context_window_minutes: int,
    passive_participation: bool,
    time_display_format: TimeDisplayFormat,
    room_chunk_size: int,
) -> WebexConfig:
    return WebexConfig(
        webex_token=webex_token or "",
        user_email=user_email or "",
        target_date=date,
        context_window_minutes=context_window_minutes,
        passive_participation=passive_participation,
        time_display_format=time_display_format.value,
        room_chunk_size=room_chunk_size,
    )


def _build_github_config(
    *,
    date: datetime,
    github_token: str | None,
    github_api_url: str,
    github_graphql_url: str | None,
    github_user: str | None,
    org: list[str] | None,
    repo: list[str] | None,
    include_types: set[ChangeType],
    safe_rate: bool,
) -> GithubConfig:
    return GithubConfig(
        github_token=github_token,
        target_date=date,
        api_url=github_api_url,
        graphql_url=github_graphql_url,
        user=github_user,
        org_filters=org or [],
        repo_filters=repo or [],
        include_types=include_types,
        safe_rate=safe_rate,
    )


def _execute_for_date(
    *,
    date: datetime,
    webex_active: bool,
    github_active: bool,
    webex_args: dict,
    github_args: dict,
) -> None:
    from summarizer.common.console_ui import print_date_header

    print_date_header(date)
    if webex_active:
        wcfg = _build_webex_config(date=date, **webex_args)
        _run_webex_for_date(wcfg, date_header=False)
    if github_active:
        gcfg = _build_github_config(date=date, **github_args)
        _run_github_for_date(gcfg, date_header=False)


@app.command()
def main(
    # Webex (optional)
    user_email: Annotated[
        str | None,
        typer.Option(envvar="USER_EMAIL", help="Webex user email"),
    ] = None,
    webex_token: Annotated[
        str | None,
        typer.Option(
            envvar="WEBEX_TOKEN",
            help=(
                "Webex access token (see https://developer.webex.com/docs/getting-started)"
            ),
            hide_input=True,
        ),
    ] = None,
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
    # GitHub (all optional; presence of token activates)
    github_token: Annotated[
        str | None,
        typer.Option(envvar="GITHUB_TOKEN", help="GitHub token"),
    ] = None,
    github_api_url: Annotated[
        str,
        typer.Option(
            envvar="GITHUB_API_URL",
            help="GitHub REST API base URL",
        ),
    ] = "https://api.github.com",
    github_graphql_url: Annotated[
        str | None,
        typer.Option(
            envvar="GITHUB_GRAPHQL_URL",
            help="GitHub GraphQL URL",
        ),
    ] = None,
    github_user: Annotated[
        str | None,
        typer.Option(
            envvar="GITHUB_USER",
            help="GitHub login (optional)",
        ),
    ] = None,
    org: Annotated[
        str | None,
        typer.Option(
            "--org",
            help="Restrict GitHub to these orgs (comma-separated)",
        ),
    ] = None,
    repo: Annotated[
        str | None,
        typer.Option(
            "--repo",
            help="Restrict GitHub to these repos (owner/name, comma-separated)",
        ),
    ] = None,
    include: Annotated[
        str | None,
        typer.Option(
            "--include",
            help="Which change types to include (csv)",
        ),
    ] = None,
    exclude: Annotated[
        str | None,
        typer.Option(
            "--exclude",
            help="Which change types to exclude (csv)",
        ),
    ] = None,
    safe_rate: Annotated[
        bool, typer.Option(help="Back off when GitHub rate is low")
    ] = False,
    # Platform control flags
    no_webex: Annotated[
        bool, typer.Option("--no-webex", help="Disable Webex processing")
    ] = False,
    no_github: Annotated[
        bool, typer.Option("--no-github", help="Disable GitHub processing")
    ] = False,
) -> None:
    """Summarizer CLI (unified Webex + GitHub)."""
    if debug is True:
        logger.setLevel(logging.DEBUG)
        logger.debug("Debug logging enabled")

    parsed_target_date, parsed_start_date, parsed_end_date, mode = (
        _validate_and_parse_dates(target_date, start_date, end_date)
    )

    webex_active = bool(webex_token and user_email) and not no_webex
    github_active = bool(github_token) and not no_github
    if not webex_active and not github_active:
        typer.echo(
            "[red]No platforms are active. Either provide Webex and/or GitHub "
            "credentials, or remove --no-webex/--no-github flags if credentials "
            "are provided.[/red]"
        )
        raise typer.Exit(1)

    if mode == "range":
        # Iterate over date range (inclusive)
        current = parsed_start_date
        if current is None or parsed_end_date is None:
            raise ValueError(
                "Both start_date and end_date must be provided for range mode"
            )
        include_types = _parse_change_types(_split_csv(include))
        exclude_types = _parse_change_types(_split_csv(exclude))
        active_types = include_types - exclude_types
        webex_args = dict(
            webex_token=webex_token,
            user_email=user_email,
            context_window_minutes=context_window_minutes,
            passive_participation=passive_participation,
            time_display_format=time_display_format,
            room_chunk_size=room_chunk_size,
        )
        github_args = dict(
            github_token=github_token,
            github_api_url=github_api_url,
            github_graphql_url=github_graphql_url,
            github_user=github_user,
            org=_split_csv(org),
            repo=_split_csv(repo),
            include_types=active_types,
            safe_rate=safe_rate,
        )
        while current <= parsed_end_date:
            _execute_for_date(
                date=current,
                webex_active=webex_active,
                github_active=github_active,
                webex_args=webex_args,
                github_args=github_args,
            )
            current += timedelta(days=1)
        return

    # Single date mode
    if parsed_target_date is None:
        raise ValueError("Target date must be provided for single date mode")
    # Single date: print date header once and run selected platforms
    include_types = _parse_change_types(_split_csv(include))
    exclude_types = _parse_change_types(_split_csv(exclude))
    active_types = include_types - exclude_types
    webex_args = dict(
        webex_token=webex_token,
        user_email=user_email,
        context_window_minutes=context_window_minutes,
        passive_participation=passive_participation,
        time_display_format=time_display_format,
        room_chunk_size=room_chunk_size,
    )
    github_args = dict(
        github_token=github_token,
        github_api_url=github_api_url,
        github_graphql_url=github_graphql_url,
        github_user=github_user,
        org=_split_csv(org),
        repo=_split_csv(repo),
        include_types=active_types,
        safe_rate=safe_rate,
    )
    _execute_for_date(
        date=parsed_target_date,
        webex_active=webex_active,
        github_active=github_active,
        webex_args=webex_args,
        github_args=github_args,
    )


if __name__ == "__main__":
    setup_logging()
    app()
