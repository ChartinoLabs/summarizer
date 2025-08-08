"""GitHub-specific configuration."""

from __future__ import annotations

from datetime import datetime
from typing import Iterable, Literal

from summarizer.common.config import BaseConfig
from summarizer.common.models import ChangeType


def _normalize_repeatable(value: str | None) -> list[str]:
    if not value:
        return []
    # comma or whitespace separated
    parts = [p.strip() for p in value.replace("\n", ",").replace(" ", ",").split(",")]
    return [p for p in parts if p]


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
            - user_email is not relevant for GitHub; it is accepted to satisfy BaseConfig.
            - If github_token is None, this config indicates GitHub is inactive.
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

    @classmethod
    def from_env(
        cls,
        *,
        target_date: datetime,
        user_email: str = "",
        env: dict[str, str] | None = None,
    ) -> "GithubConfig":
        e = env or {}
        token = e.get("GITHUB_TOKEN")
        api_url = e.get("GITHUB_API_URL", "https://api.github.com")
        graphql_url = e.get("GITHUB_GRAPHQL_URL")
        user = e.get("GITHUB_USER")
        org_filters = _normalize_repeatable(e.get("GITHUB_ORGS"))
        repo_filters = _normalize_repeatable(e.get("GITHUB_REPOS"))
        include_raw = _normalize_repeatable(e.get("GITHUB_INCLUDE"))
        include_types = _parse_include_types(include_raw) if include_raw else set(ChangeType)
        safe_rate = e.get("GITHUB_SAFE_RATE", "false").lower() in {"1", "true", "yes"}
        return cls(
            github_token=token,
            target_date=target_date,
            user_email=user_email,
            api_url=api_url,
            graphql_url=graphql_url,
            user=user,
            org_filters=org_filters,
            repo_filters=repo_filters,
            include_types=include_types,
            safe_rate=safe_rate,
        )

    def is_active(self) -> bool:
        """Return True if GitHub credentials are present and should be used."""
        return bool(self.github_token)

    def get_platform_name(self) -> str:
        return "github"


# ---------------------
# Helpers (parsing)
# ---------------------

_INCLUDE_SYNONYMS: dict[str, ChangeType] = {
    # commits
    "commit": ChangeType.COMMIT,
    "commits": ChangeType.COMMIT,
    # issues
    "issue": ChangeType.ISSUE,
    "issues": ChangeType.ISSUE,
    # pull requests
    "pr": ChangeType.PULL_REQUEST,
    "prs": ChangeType.PULL_REQUEST,
    "pull_request": ChangeType.PULL_REQUEST,
    "pull_requests": ChangeType.PULL_REQUEST,
    # issue comments
    "issue_comment": ChangeType.ISSUE_COMMENT,
    "issue_comments": ChangeType.ISSUE_COMMENT,
    # pr comments
    "pr_comment": ChangeType.PR_COMMENT,
    "pr_comments": ChangeType.PR_COMMENT,
    "pull_request_comment": ChangeType.PR_COMMENT,
    "pull_request_comments": ChangeType.PR_COMMENT,
    # reviews
    "review": ChangeType.REVIEW,
    "reviews": ChangeType.REVIEW,
}


def _parse_include_types(raw: list[str]) -> set[ChangeType]:
    include: set[ChangeType] = set()
    for item in raw:
        key = (item or "").strip().lower()
        if not key:
            continue
        ct = _INCLUDE_SYNONYMS.get(key)
        if ct is not None:
            include.add(ct)
            continue
        # Allow direct enum names (e.g., COMMIT) for power users
        try:
            include.add(ChangeType[key.upper()])
        except Exception:
            # Unknown value → ignore rather than raising; keeps CLI forgiving
            pass
    return include


