"""GitHub runner implementation (skeleton)."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta, tzinfo

from summarizer.common.console_ui import console
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
        super().__init__(config)
        self.config: GithubConfig = config
        self.client: GithubClient | None = None

    def connect(self) -> None:
        self.client = GithubClient(self.config)
        try:
            identity = self.client.get_viewer()
        except Exception as exc:  # refined auth errors will be implemented later
            console.print("\n[bold red]Error: Invalid GitHub credentials or endpoint.[/]")
            logger.error("GitHub authentication failed: %s", exc)
            raise
        console.log(f"Connected to GitHub as [bold green]{identity.login}[/]")

    # Override BaseRunner.run to avoid conversation grouping
    def run(self, date_header: bool = False) -> None:  # type: ignore[override]
        local_tz = datetime.now().astimezone().tzinfo or UTC
        if date_header:
            from summarizer.common.console_ui import print_date_header

            print_date_header(self.config.target_date)

        with console.status("[bold green]Connecting to APIs...[/]"):
            self.connect()

        # Determine start/end for the given date in local timezone
        target = self.config.target_date.astimezone(local_tz)
        start = datetime(target.year, target.month, target.day, tzinfo=local_tz)
        end = start + timedelta(days=1)

        if not self.client:
            raise RuntimeError("Must call connect() before run()")

        changes = self.client.get_changes(start, end)

        # Placeholder rendering until console helpers are added
        if not changes:
            console.print("[yellow]No GitHub changes found for this date.[/]")
            return

        console.print(f"[bold]GitHub Changes:[/] {len(changes)} items")
        for ch in changes:
            ts = ch.timestamp.astimezone(local_tz).strftime("%Y-%m-%d %H:%M:%S")
            console.print(f"- [{ch.type.value}] {ts} {ch.repo_full_name}: {ch.title}")


