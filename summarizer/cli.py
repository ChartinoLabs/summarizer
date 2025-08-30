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
from summarizer.webex.oauth import WebexOAuthApp, WebexOAuthClient
from summarizer.webex.runner import WebexRunner

# Load environment variables from .env before initializing the Typer app
load_dotenv()

# Set up logging
setup_logging()
logger = logging.getLogger(__name__)

app = typer.Typer(pretty_exceptions_enable=False)

# Create subcommand for OAuth management
webex_app = typer.Typer(help="Webex OAuth authentication management")
app.add_typer(webex_app, name="webex")


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
        except (KeyError, ValueError) as e:
            # Log unknown change type values for debugging
            import logging

            logging.debug(f"Unknown change type '{key}': {e}")
            continue
    return result or set(ChangeType)


def _split_csv(value: str | None) -> list[str] | None:
    if value is None:
        return None
    parts = [p.strip() for p in value.replace("\n", ",").split(",")]
    return [p for p in parts if p]


def _build_webex_args(
    *,
    webex_token: str | None,
    user_email: str | None,
    webex_oauth_client_id: str | None,
    webex_oauth_client_secret: str | None,
    context_window_minutes: int,
    passive_participation: bool,
    time_display_format: TimeDisplayFormat,
    room_chunk_size: int,
) -> dict:
    """Build Webex arguments dictionary for _execute_for_date."""
    return dict(
        webex_token=webex_token,
        user_email=user_email,
        oauth_client_id=webex_oauth_client_id,
        oauth_client_secret=webex_oauth_client_secret,
        context_window_minutes=context_window_minutes,
        passive_participation=passive_participation,
        time_display_format=time_display_format,
        room_chunk_size=room_chunk_size,
    )


def _build_github_args(
    *,
    github_token: str | None,
    github_api_url: str,
    github_graphql_url: str | None,
    github_user: str | None,
    org: list[str] | None,
    repo: list[str] | None,
    include_types: set[ChangeType],
    safe_rate: bool,
) -> dict:
    """Build GitHub arguments dictionary for _execute_for_date."""
    return dict(
        github_token=github_token,
        github_api_url=github_api_url,
        github_graphql_url=github_graphql_url,
        github_user=github_user,
        org=org,
        repo=repo,
        include_types=include_types,
        safe_rate=safe_rate,
    )


def _process_change_types(include: str | None, exclude: str | None) -> set[ChangeType]:
    """Process include/exclude change type filters."""
    include_types = _parse_change_types(_split_csv(include))
    exclude_types = _parse_change_types(_split_csv(exclude))
    return include_types - exclude_types


def _build_webex_config(
    *,
    date: datetime,
    webex_token: str | None,
    user_email: str | None,
    oauth_client_id: str | None,
    oauth_client_secret: str | None,
    context_window_minutes: int,
    passive_participation: bool,
    time_display_format: TimeDisplayFormat,
    room_chunk_size: int,
) -> WebexConfig:
    return WebexConfig(
        user_email=user_email or "",
        target_date=date,
        webex_token=webex_token,
        oauth_client_id=oauth_client_id,
        oauth_client_secret=oauth_client_secret,
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


def _setup_debug_logging(debug: bool) -> None:
    """Configure debug logging when requested."""
    if not debug:
        return

    # Set debug level for all relevant loggers
    logging.getLogger().setLevel(logging.DEBUG)
    logging.getLogger("summarizer.github.client").setLevel(logging.DEBUG)
    logging.getLogger("summarizer.github.runner").setLevel(logging.DEBUG)
    logger.setLevel(logging.DEBUG)

    # Add console handler for debug output
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.DEBUG)
    console_formatter = logging.Formatter("%(name)s: %(levelname)s: %(message)s")
    console_handler.setFormatter(console_formatter)
    logging.getLogger().addHandler(console_handler)

    logger.debug("Debug logging enabled")


def _determine_active_platforms(
    webex_token: str | None,
    user_email: str | None,
    webex_oauth_client_id: str | None,
    webex_oauth_client_secret: str | None,
    github_token: str | None,
    no_webex: bool,
    no_github: bool,
) -> tuple[bool, bool]:
    """Determine which platforms are active based on credentials and flags."""
    # Webex is active if user_email is provided AND either:
    # 1. Manual token is provided, OR
    # 2. OAuth credentials are provided, OR
    # 3. OAuth credentials are stored from previous authentication
    webex_has_auth = False
    if user_email:
        if webex_token:
            webex_has_auth = True
        elif webex_oauth_client_id and webex_oauth_client_secret:
            # Check if we have valid OAuth config or stored credentials
            try:
                from summarizer.webex.oauth import WebexOAuthApp, WebexOAuthClient

                app_config = WebexOAuthApp(
                    client_id=webex_oauth_client_id,
                    client_secret=webex_oauth_client_secret,
                )
                oauth_client = WebexOAuthClient(app_config)
                # Check if we can get a valid token (either stored or can be refreshed)
                webex_has_auth = bool(oauth_client.get_valid_access_token())
            except Exception:
                webex_has_auth = False

    webex_active = webex_has_auth and not no_webex
    github_active = bool(github_token) and not no_github

    if not webex_active and not github_active:
        typer.echo(
            "[red]No platforms are active. For Webex, provide either:\n"
            "  1. --webex-token and --user-email, OR\n"
            "  2. --webex-oauth-client-id, --webex-oauth-client-secret, --user-email, and run 'summarizer webex login'\n"
            "For GitHub, provide --github-token.[/red]"
        )
        raise typer.Exit(1)

    return webex_active, github_active


def _execute_range_mode(
    parsed_start_date: datetime,
    parsed_end_date: datetime,
    webex_active: bool,
    github_active: bool,
    webex_args: dict,
    github_args: dict,
) -> None:
    """Execute processing for a date range."""
    if parsed_start_date is None or parsed_end_date is None:
        raise ValueError("Both start_date and end_date must be provided for range mode")

    current = parsed_start_date
    while current <= parsed_end_date:
        _execute_for_date(
            date=current,
            webex_active=webex_active,
            github_active=github_active,
            webex_args=webex_args,
            github_args=github_args,
        )
        current += timedelta(days=1)


def _execute_single_date_mode(
    parsed_target_date: datetime,
    webex_active: bool,
    github_active: bool,
    webex_args: dict,
    github_args: dict,
) -> None:
    """Execute processing for a single date."""
    if parsed_target_date is None:
        raise ValueError("Target date must be provided for single date mode")

    _execute_for_date(
        date=parsed_target_date,
        webex_active=webex_active,
        github_active=github_active,
        webex_args=webex_args,
        github_args=github_args,
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


@webex_app.command("login")
def webex_oauth_login(
    client_id: Annotated[
        str | None,
        typer.Option(
            envvar="WEBEX_OAUTH_CLIENT_ID", help="Webex OAuth application client ID"
        ),
    ] = None,
    client_secret: Annotated[
        str | None,
        typer.Option(
            envvar="WEBEX_OAUTH_CLIENT_SECRET",
            help="Webex OAuth application client secret",
            hide_input=True,
        ),
    ] = None,
    redirect_uri: Annotated[
        str, typer.Option(help="OAuth redirect URI")
    ] = "http://localhost:8080/callback",
) -> None:
    """Authenticate with Webex using OAuth 2.0 flow."""
    if not client_id:
        client_id = typer.prompt("Webex OAuth Client ID")
    if not client_secret:
        client_secret = typer.prompt("Webex OAuth Client Secret", hide_input=True)

    try:
        app_config = WebexOAuthApp(
            client_id=client_id, client_secret=client_secret, redirect_uri=redirect_uri
        )
        oauth_client = WebexOAuthClient(app_config)

        # Start interactive authentication
        credentials = oauth_client.start_interactive_auth()

        typer.echo(f"✅ Successfully authenticated with Webex!")
        typer.echo(f"Access token expires: {credentials.expires_at}")
        typer.echo(f"Credentials saved to: {oauth_client.credentials_file}")

    except Exception as e:
        typer.echo(f"❌ Authentication failed: {e}", err=True)
        raise typer.Exit(1)


@webex_app.command("logout")
def webex_oauth_logout(
    client_id: Annotated[
        str | None,
        typer.Option(
            envvar="WEBEX_OAUTH_CLIENT_ID", help="Webex OAuth application client ID"
        ),
    ] = None,
    client_secret: Annotated[
        str | None,
        typer.Option(
            envvar="WEBEX_OAUTH_CLIENT_SECRET",
            help="Webex OAuth application client secret",
            hide_input=True,
        ),
    ] = None,
) -> None:
    """Remove stored Webex OAuth credentials."""
    if not client_id:
        client_id = typer.prompt("Webex OAuth Client ID")
    if not client_secret:
        client_secret = typer.prompt("Webex OAuth Client Secret", hide_input=True)

    try:
        app_config = WebexOAuthApp(client_id=client_id, client_secret=client_secret)
        oauth_client = WebexOAuthClient(app_config)

        if oauth_client.credentials_file.exists():
            oauth_client.revoke_credentials()
            typer.echo("✅ Successfully logged out of Webex")
        else:
            typer.echo("ℹ️  No stored credentials found")

    except Exception as e:
        typer.echo(f"❌ Logout failed: {e}", err=True)
        raise typer.Exit(1)


@webex_app.command("status")
def webex_oauth_status(
    client_id: Annotated[
        str | None,
        typer.Option(
            envvar="WEBEX_OAUTH_CLIENT_ID", help="Webex OAuth application client ID"
        ),
    ] = None,
    client_secret: Annotated[
        str | None,
        typer.Option(
            envvar="WEBEX_OAUTH_CLIENT_SECRET",
            help="Webex OAuth application client secret",
            hide_input=True,
        ),
    ] = None,
) -> None:
    """Check Webex OAuth authentication status."""
    if not client_id:
        client_id = typer.prompt("Webex OAuth Client ID")
    if not client_secret:
        client_secret = typer.prompt("Webex OAuth Client Secret", hide_input=True)

    try:
        app_config = WebexOAuthApp(client_id=client_id, client_secret=client_secret)
        oauth_client = WebexOAuthClient(app_config)

        credentials = oauth_client.load_credentials()
        if not credentials:
            typer.echo("❌ Not authenticated with Webex OAuth")
            typer.echo("Run 'summarizer webex login' to authenticate")
            return

        if credentials.is_expired():
            typer.echo("⚠️  Access token is expired")
            try:
                oauth_client.refresh_access_token(credentials)
                typer.echo("✅ Token refreshed successfully")
                credentials = oauth_client.load_credentials()
            except Exception as e:
                typer.echo(f"❌ Token refresh failed: {e}")
                typer.echo("Run 'summarizer webex login' to re-authenticate")
                return

        typer.echo("✅ Authenticated with Webex OAuth")
        typer.echo(f"Access token expires: {credentials.expires_at}")
        typer.echo(f"Scopes: {credentials.scope}")

    except Exception as e:
        typer.echo(f"❌ Status check failed: {e}", err=True)
        raise typer.Exit(1)


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    # Webex (optional)
    user_email: Annotated[
        str | None,
        typer.Option(envvar="USER_EMAIL", help="Webex user email"),
    ] = None,
    webex_token: Annotated[
        str | None,
        typer.Option(
            envvar="WEBEX_TOKEN",
            help="Webex access token (legacy - prefer OAuth)",
            hide_input=True,
        ),
    ] = None,
    webex_oauth_client_id: Annotated[
        str | None,
        typer.Option(
            envvar="WEBEX_OAUTH_CLIENT_ID", help="Webex OAuth application client ID"
        ),
    ] = None,
    webex_oauth_client_secret: Annotated[
        str | None,
        typer.Option(
            envvar="WEBEX_OAUTH_CLIENT_SECRET",
            help="Webex OAuth application client secret",
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

    # If a subcommand was invoked, don't run the main logic
    if ctx.invoked_subcommand is not None:
        return

    # Setup debug logging if requested
    _setup_debug_logging(debug)

    # Parse and validate dates
    parsed_target_date, parsed_start_date, parsed_end_date, mode = (
        _validate_and_parse_dates(target_date, start_date, end_date)
    )

    # Determine which platforms are active
    webex_active, github_active = _determine_active_platforms(
        webex_token,
        user_email,
        webex_oauth_client_id,
        webex_oauth_client_secret,
        github_token,
        no_webex,
        no_github,
    )

    # Build platform arguments
    active_types = _process_change_types(include, exclude)
    webex_args = _build_webex_args(
        webex_token=webex_token,
        user_email=user_email,
        webex_oauth_client_id=webex_oauth_client_id,
        webex_oauth_client_secret=webex_oauth_client_secret,
        context_window_minutes=context_window_minutes,
        passive_participation=passive_participation,
        time_display_format=time_display_format,
        room_chunk_size=room_chunk_size,
    )
    github_args = _build_github_args(
        github_token=github_token,
        github_api_url=github_api_url,
        github_graphql_url=github_graphql_url,
        github_user=github_user,
        org=_split_csv(org),
        repo=_split_csv(repo),
        include_types=active_types,
        safe_rate=safe_rate,
    )

    # Execute based on mode
    if mode == "range":
        _execute_range_mode(
            parsed_start_date,
            parsed_end_date,
            webex_active,
            github_active,
            webex_args,
            github_args,
        )
    else:
        _execute_single_date_mode(
            parsed_target_date,
            webex_active,
            github_active,
            webex_args,
            github_args,
        )


if __name__ == "__main__":
    setup_logging()
    app()
