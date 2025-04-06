"""Type definitions for the webex-summarizer application."""

from datetime import datetime
from typing import TypedDict


class MessageData(TypedDict):
    """Message data structure."""

    time: datetime
    space: str
    text: str


class CommitData(TypedDict):
    """Commit data structure."""

    time: datetime
    repo: str
    message: str
    sha: str
