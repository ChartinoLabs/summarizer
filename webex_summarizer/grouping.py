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
    if not messages:
        return []

    # Sort messages by timestamp
    messages = sorted(messages, key=lambda m: m.timestamp)
    conversations: list[Conversation] = []
    used_indices: set[int] = set()
    conversation_id_counter = 1

    for i, msg in enumerate(messages):
        if i in used_indices:
            continue
        # Only start a conversation window if the user sent the message, or if passive
        # is enabled
        is_sent_by_user = (
            msg.sender.id == messages[0].sender.id
        )  # Assume first sender is user
        if not is_sent_by_user and not include_passive:
            continue
        window_start = msg.timestamp - context_window
        window_end = msg.timestamp + context_window
        # Collect all messages within the window
        convo_msgs = [msg]
        used_indices.add(i)
        for j in range(i + 1, len(messages)):
            m2 = messages[j]
            if window_start <= m2.timestamp <= window_end:
                convo_msgs.append(m2)
                used_indices.add(j)
            elif m2.timestamp > window_end:
                break
        # Build conversation participants
        participants = {m.sender.id: m.sender for m in convo_msgs}
        conversation = Conversation(
            id=f"dm-{conversation_id_counter}",
            space_id=msg.space_id,
            space_type=msg.space_type,
            participants=list(participants.values()),
            messages=convo_msgs,
            start_time=convo_msgs[0].timestamp,
            end_time=convo_msgs[-1].timestamp,
            duration_seconds=int(
                (convo_msgs[-1].timestamp - convo_msgs[0].timestamp).total_seconds()
            ),
            is_threaded=False,
        )
        conversations.append(conversation)
        conversation_id_counter += 1
    return conversations


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
