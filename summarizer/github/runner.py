"""GitHub runner implementation (skeleton)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo

from summarizer.common.console_ui import (
    console,
    display_changes,
    display_changes_summary,
)
from summarizer.common.models import Message
from summarizer.common.runner import BaseRunner
from summarizer.github.client import GithubClient
from summarizer.github.config import GithubConfig

logger = logging.getLogger(__name__)


class GithubRunner(BaseRunner):
    """GitHub-specific runner implementation.

    For GitHub we do not use the conversation grouping from Webex. Instead, we
    collect Change items and render them via console helpers (to be added).
    """

    def __init__(self, config: GithubConfig) -> None:
        """Initialize the GitHub runner with `GithubConfig`."""
        super().__init__(config)
        self.config: GithubConfig = config
        self.client: GithubClient | None = None

    def connect(self) -> None:
        """Connect to GitHub and validate credentials."""
        self.client = GithubClient(self.config)
        try:
            identity = self.client.get_viewer()
        except Exception as exc:  # refined auth errors will be implemented later
            console.print(
                "\n[bold red]Error: Invalid GitHub credentials or endpoint.[/]"
            )
            logger.error("GitHub authentication failed: %s", exc)
            raise
        console.log(f"Connected to GitHub as [bold green]{identity.login}[/]")

    # Override BaseRunner.run to avoid conversation grouping
    def run(self, date_header: bool = False) -> None:  # type: ignore[override]
        """Execute the GitHub flow for a single date."""
        if date_header:
            from summarizer.common.console_ui import print_date_header

            print_date_header(self.config.target_date)

        with console.status("[bold green]Connecting to APIs...[/]"):
            self.connect()

        # Use Pacific Time date boundaries to match GitHub's contribution calendar
        # GitHub uses Pacific Time (US/Pacific) for determining which day
        # contributions belong to. This prevents timezone-related date leakage.
        github_tz = ZoneInfo('US/Pacific')
        target_date = self.config.target_date.date()  # Get just the date part

        # Create the date boundaries in Pacific Time, then convert to UTC
        pt_start = datetime.combine(
            target_date, datetime.min.time()
        ).replace(tzinfo=github_tz)
        pt_end = pt_start + timedelta(days=1)

        # Convert to UTC for the API calls
        start = pt_start.astimezone(UTC)
        end = pt_end.astimezone(UTC)

        if not self.client:
            raise RuntimeError("Must call connect() before run()")

        changes = self.client.get_changes(start, end)

        display_changes(changes)
        display_changes_summary(changes)

    # Unused by GitHub runner; implemented to satisfy abstract base class
    def get_activity(self, date: datetime, local_tz: tzinfo) -> list[Message]:  # type: ignore[override]
        """Unused for GitHub; return empty list to satisfy base contract."""
        return []

    def get_user_id(self) -> str:  # type: ignore[override]
        """Unused for GitHub; return configured login if present."""
        return self.config.user or ""
