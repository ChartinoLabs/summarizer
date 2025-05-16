"""Grouping logic for messages."""

from datetime import timedelta

from .models import Conversation, Message, SpaceType


def group_dm_conversations(
    messages: list[Message], context_window: timedelta, include_passive: bool = False
) -> list[Conversation]:
    """Group messages in DM space into conversations based on time context window.

    Only includes conversations where the authenticated user sent at least one message,
    unless include_passive is True.
    """
    if not messages:
        return []

    # Group messages by space_id first
    from collections import defaultdict

    messages_by_space: dict[str, list[Message]] = defaultdict(list)
    for msg in messages:
        messages_by_space[msg.space_id].append(msg)

    conversations: list[Conversation] = []
    conversation_id_counter = 1

    for space_messages in messages_by_space.values():
        # Sort messages by timestamp within each space
        space_messages = sorted(space_messages, key=lambda m: m.timestamp)
        used_indices: set[int] = set()
        for i, msg in enumerate(space_messages):
            if i in used_indices:
                continue
            # Only start a conversation window if the user sent the message, or
            # if passive is enabled
            is_sent_by_user = (
                msg.sender.id == space_messages[0].sender.id
            )  # Assume first sender is user
            if not is_sent_by_user and not include_passive:
                continue
            window_start = msg.timestamp - context_window
            window_end = msg.timestamp + context_window
            # Collect all messages within the window
            convo_msgs = [msg]
            used_indices.add(i)
            for j in range(i + 1, len(space_messages)):
                m2 = space_messages[j]
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


def _group_threaded_messages(
    messages: list[Message],
) -> tuple[dict[str, list[Message]], dict[str, str]]:
    """Group threaded messages by thread ID and return thread messages/owners."""
    thread_conversations: dict[str, list[Message]] = {}
    thread_owners: dict[str, str] = {}  # thread_id -> original poster id
    for msg in messages:
        if msg.thread is not None:
            thread_id = msg.thread.id
            if thread_id not in thread_conversations:
                thread_conversations[thread_id] = []
                thread_owners[thread_id] = msg.thread.original_poster.id
            thread_conversations[thread_id].append(msg)
    return thread_conversations, thread_owners


def _create_thread_conversations(
    thread_conversations: dict[str, list[Message]],
    thread_owners: dict[str, str],
    user_id: str,
    conversation_id_start: int = 1,
) -> tuple[list[Conversation], int]:
    """Create Conversation objects for threads the user participated in."""
    conversations: list[Conversation] = []
    conversation_id_counter = conversation_id_start
    for thread_id, msgs in thread_conversations.items():
        user_participated = any(m.sender.id == user_id for m in msgs)
        if not user_participated:
            continue
        # Always include the original post
        original_poster_id = thread_owners[thread_id]
        original_post = next(
            (m for m in msgs if m.sender.id == original_poster_id), None
        )
        if original_post and original_post not in msgs:
            msgs.insert(0, original_post)
        participants = {m.sender.id: m.sender for m in msgs}
        conversation = Conversation(
            id=f"group-thread-{conversation_id_counter}",
            space_id=msgs[0].space_id,
            space_type=msgs[0].space_type,
            participants=list(participants.values()),
            messages=msgs,
            start_time=msgs[0].timestamp,
            end_time=msgs[-1].timestamp,
            duration_seconds=int(
                (msgs[-1].timestamp - msgs[0].timestamp).total_seconds()
            ),
            is_threaded=True,
        )
        conversations.append(conversation)
        conversation_id_counter += 1
    return conversations, conversation_id_counter


def _group_non_threaded_messages(
    messages: list[Message],
    context_window: timedelta,
    user_id: str,
    used_indices: set[int],
    conversation_id_start: int = 1,
) -> list[Conversation]:
    """Group non-threaded messages into conversations using context window logic."""
    conversations: list[Conversation] = []
    conversation_id_counter = conversation_id_start
    messages = sorted(messages, key=lambda m: m.timestamp)
    for i, msg in enumerate(messages):
        if i in used_indices:
            continue
        if msg.thread is not None:
            continue  # Already handled
        if msg.sender.id != user_id:
            continue
        window_start = msg.timestamp - context_window
        window_end = msg.timestamp + context_window
        convo_msgs = [msg]
        used_indices.add(i)
        for j in range(i + 1, len(messages)):
            m2 = messages[j]
            if m2.thread is not None:
                continue  # Skip threaded messages
            if window_start <= m2.timestamp <= window_end:
                convo_msgs.append(m2)
                used_indices.add(j)
            elif m2.timestamp > window_end:
                break
        participants = {m.sender.id: m.sender for m in convo_msgs}
        conversation = Conversation(
            id=f"group-nonthread-{conversation_id_counter}",
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
    - Threaded: If the user starts or replies to a thread, group all messages in that
      thread.
      - Always include the original post of the thread.
      - If the user replies to multiple threads by the same user, group them together.
    - Non-threaded: Use context window logic as in DMs, but only for messages sent by
      the user.
    - Each message can only belong to one conversation.
    """
    if not messages:
        return []
    messages = sorted(messages, key=lambda m: m.timestamp)
    user_id = messages[0].sender.id if messages else None
    if user_id is None:
        return []
    used_indices: set[int] = set()
    # Threaded
    thread_conversations, thread_owners = _group_threaded_messages(messages)
    thread_convos, next_id = _create_thread_conversations(
        thread_conversations, thread_owners, user_id, conversation_id_start=1
    )
    for i, msg in enumerate(messages):
        if msg.thread is not None:
            used_indices.add(i)
    # Non-threaded
    nonthread_convos = _group_non_threaded_messages(
        messages, context_window, user_id, used_indices, conversation_id_start=next_id
    )
    return thread_convos + nonthread_convos


def group_all_conversations(
    messages: list[Message], context_window: timedelta, include_passive: bool = False
) -> list[Conversation]:
    """Group all messages (DM and group spaces) into conversations.

    Dispatches to the appropriate grouping function based on space type.
    """
    if not messages:
        return []
    dms = [m for m in messages if m.space_type == SpaceType.DM]
    groups = [m for m in messages if m.space_type == SpaceType.GROUP]
    conversations: list[Conversation] = []
    if dms:
        conversations.extend(
            group_dm_conversations(dms, context_window, include_passive=include_passive)
        )
    if groups:
        conversations.extend(group_group_conversations(groups, context_window))
    return conversations
