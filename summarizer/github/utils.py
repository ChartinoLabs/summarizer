"""GitHub client utility functions."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from summarizer.common.models import ChangeType

logger = logging.getLogger(__name__)


def extract_number(api_url: str | None) -> str | None:
    """Extract issue/PR number from GitHub API URL."""
    if not api_url:
        return None
    try:
        # Issue URL ends with /issues/{number} or PR URL with /pulls/{number}
        return api_url.rstrip("/").split("/")[-1]
    except (IndexError, AttributeError) as e:
        # Log malformed URL for debugging
        logger.debug(f"Failed to extract number from URL '{api_url}': {e}")
        return None


def ensure_utc(dt: datetime) -> datetime:
    """Ensure datetime is in UTC timezone."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def parse_iso(value: str | None) -> datetime | None:
    """Parse ISO-8601 datetime string to datetime object."""
    if not value:
        return None
    try:
        # GraphQL returns ISO-8601; datetime.fromisoformat supports Z via replace
        v = value.replace("Z", "+00:00")
        return datetime.fromisoformat(v)
    except (ValueError, AttributeError) as e:
        # Log malformed ISO date for debugging
        logger.debug(f"Failed to parse ISO date '{value}': {e}")
        return None


def change_type_from_name(name: str) -> ChangeType:
    """Convert string name to ChangeType enum."""
    return ChangeType[name]


def to_utc_iso(dt: datetime) -> str:
    """Convert datetime to UTC ISO-8601 string."""
    return ensure_utc(dt).isoformat().replace("+00:00", "Z")


def parse_link_header(link_header: str | None) -> str | None:
    """Parse GitHub Link header to extract 'next' URL."""
    if not link_header:
        return None
    for part in link_header.split(","):
        if 'rel="next"' in part:
            # Extract URL from <URL>; rel="next"
            start = part.find("<")
            end = part.find(">")
            if start != -1 and end != -1:
                return part[start + 1 : end]
    return None
