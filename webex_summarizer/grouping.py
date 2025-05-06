"""Grouping logic for messages."""

from datetime import timedelta

from .models import Conversation, Message


def group_dm_conversations(
    messages: list[Message], context_window: timedelta, include_passive: bool = False
) -> list[Conversation]:
    """Group messages in DM space into conversations based on time context window.

    Only includes conversations where the authenticated user sent at least one message,
    unless include_passive is True.
    """
    # Implementation to be added
    return []


def group_group_conversations(
    messages: list[Message], context_window: timedelta
) -> list[Conversation]:
    """Group messages in a group space into conversations using heuristics.

    Heuristics:
    - Threads are grouped together.
    - Non-threaded messages are grouped together.
    """
    # Implementation to be added
    return []


def group_all_conversations(
    messages: list[Message], context_window: timedelta, include_passive: bool = False
) -> list[Conversation]:
    """Group all messages (DM and group spaces) into conversations.

    Dispatches to the appropriate grouping function based on space type.
    """
    # Implementation to be added
    return []
