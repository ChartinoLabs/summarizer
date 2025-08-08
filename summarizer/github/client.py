"""GitHub API client (skeleton).

Provides typed methods that will be easy to unit-test. Actual HTTP will be
implemented in a later task along with GraphQL/REST mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from summarizer.common.models import Change
from summarizer.github.config import GithubConfig


@dataclass
class Identity:
    """Authenticated GitHub identity information."""

    login: str


class GithubClient:
    """Thin client around GitHub GraphQL/REST.

    This class intentionally avoids importing requests for now to keep the
    scaffolding atomic and easily testable with pure unit tests. HTTP will be
    added alongside tests that mock network calls.
    """

    def __init__(self, config: GithubConfig) -> None:
        """Initialize the client with a `GithubConfig`."""
        self.config = config

    # Connection / identity
    def get_viewer(self) -> Identity:
        """Return authenticated identity. Raises on authentication failure."""
        raise NotImplementedError

    # Activity collection
    def get_changes(self, start: datetime, end: datetime) -> list[Change]:
        """Return changes between [start, end)."""
        raise NotImplementedError

    # Utilities
    @staticmethod
    def to_utc_iso(dt: datetime) -> str:
        """Convert a datetime to an ISO-8601 UTC string."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
