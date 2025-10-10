"""GitHub-specific configuration container.

This class is intentionally free of environment/CLI parsing. The CLI will pass
native primitives (str, list[str], set[ChangeType], etc.) constructed by Typer.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Literal

from summarizer.common.config import BaseConfig
from summarizer.common.models import ChangeType


class GithubConfig(BaseConfig):
    """GitHub-specific configuration."""

    def __init__(
        self,
        *,
        github_token: str | None,
        target_date: datetime,
        user_email: str = "",
        api_url: str = "https://api.github.com",
        graphql_url: str | None = None,
        user: str | None = None,
        org_filters: Iterable[str] | None = None,
        repo_filters: Iterable[str] | None = None,
        include_types: Iterable[ChangeType] | None = None,
        safe_rate: bool = False,
        context_window_minutes: int = 15,
        passive_participation: bool = False,
        time_display_format: Literal["12h", "24h"] = "12h",
    ) -> None:
        """Initialize GitHub configuration.

        Notes:
            - user_email is not relevant for GitHub; it is accepted to
              satisfy BaseConfig.
            - If github_token is None, this config indicates GitHub is
              inactive.
        """
        super().__init__(
            user_email=user_email,
            target_date=target_date,
            context_window_minutes=context_window_minutes,
            passive_participation=passive_participation,
            time_display_format=time_display_format,
        )
        self.github_token = github_token
        self.api_url = api_url.rstrip("/")
        self.graphql_url = (graphql_url or f"{self.api_url}/graphql").rstrip("/")
        self.user = user
        self.org_filters = list(org_filters or [])
        self.repo_filters = list(repo_filters or [])
        self.include_types = set(include_types or set(ChangeType))
        self.safe_rate = safe_rate

    def is_active(self) -> bool:
        """Return True if GitHub credentials are present and should be used."""
        return bool(self.github_token)

    def get_platform_name(self) -> str:
        """Return platform name for display/logging."""
        return "github"
