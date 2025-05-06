"""Data models for the application."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class MessageType(Enum):
    """The type of message."""

    TEXT = "text"
    FILE = "file"
    IMAGE = "image"
    REACTION = "reaction"
    OTHER = "other"


class SpaceType(Enum):
    """The type of space."""

    DM = "dm"
    GROUP = "group"


@dataclass
class User:
    """Data for a user."""

    id: str
    display_name: str


@dataclass
class Thread:
    """Data for a thread."""

    id: str
    original_post_id: str
    original_poster: User


@dataclass
class Message:
    """Data for a message."""

    id: str
    space_id: str
    space_type: SpaceType
    sender: User
    recipients: list[User]
    timestamp: datetime
    content: str
    message_type: MessageType
    thread: Thread | None = None
    conversation_id: str | None = None


@dataclass
class Conversation:
    """Data for a conversation."""

    id: str
    space_id: str
    space_type: SpaceType
    participants: list[User]
    messages: list[Message] = field(default_factory=list)
    start_time: datetime | None = None
    end_time: datetime | None = None
    duration_seconds: int | None = None
    is_threaded: bool = False
