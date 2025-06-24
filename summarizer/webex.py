"""Webex API interaction functions."""

import logging
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, tzinfo

from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from webexpythonsdk import WebexAPI
from webexpythonsdk.models.immutable import Message as SDKMessage, Person, Room

from .config import AppConfig
from .console_ui import console
from .models import Message, SpaceType, User

logger = logging.getLogger(__name__)


def sdk_person_to_user(person: Person) -> User:
    """Convert a Webex API Person object to a User dataclass."""
    return User(id=person.id, display_name=person.displayName)


def get_space_type(room: Room) -> SpaceType:
    """Get the type of a space from a Webex API Room object."""
    if room.type == "direct":
        return SpaceType.DM
    elif room.type == "group":
        return SpaceType.GROUP
    else:
        raise ValueError(f"Unknown space type: {room.type}")


@dataclass
class MessageAnalysisResult:
    """Result of analyzing messages for a specific date in a room."""

    room: Room
    messages: list[Message]
    last_activity: datetime | None
    had_activity_on_or_after_date: bool


class WebexClient:
    """Wrapper around Webex API client."""

    def __init__(self, config: AppConfig, client: WebexAPI | None = None) -> None:
        """Initialize with configuration."""
        self.config = config
        self._client = client or WebexAPI(access_token=config.webex_token)
        self._me: Person | None = None

    def get_me(self) -> User:
        """Get user information as a User dataclass."""
        if not self._me:
            self._me = self._client.people.me()
        return sdk_person_to_user(self._me)

    def get_rooms_active_since_date(self, date: datetime) -> list[Room]:
        """Get all rooms that have had activity since the given date."""
        active_rooms: list[Room] = []
        seen_room_ids: set[str] = set()  # Track seen room IDs
        rooms = self._client.rooms.list(
            max=self.config.room_chunk_size, sortBy="lastactivity"
        )
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Scanning rooms for activity..."),
            TextColumn("[green]Processed: {task.completed}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Scanning rooms for activity...", total=None)
            for room in rooms:
                logger.debug("Processing room: id=%s, title=%s", room.id, room.title)
                if room.id in seen_room_ids:
                    logger.debug(
                        "Room %s (ID %s) already processed, skipping...",
                        room.title,
                        room.id,
                    )
                    progress.update(task, advance=1)
                    continue
                seen_room_ids.add(room.id)
                if room.lastActivity is None:
                    progress.update(task, advance=1)
                    logger.debug(
                        "Room %s (ID %s) has no last activity date, skipping...",
                        room.title,
                        room.id,
                    )
                    continue
                if room.lastActivity.date() >= date.date():
                    logger.debug(
                        "Room %s (ID %s) has last activity at %s, which is on or "
                        "after date %s, adding to list...",
                        room.title,
                        room.id,
                        room.lastActivity,
                        date,
                    )
                    active_rooms.append(room)
                else:
                    # Still count the room as processed
                    progress.update(task, advance=1)
                    logger.debug(
                        "Room %s (ID %s) has last activity at %s, which is before "
                        "date %s, skipping...",
                        room.title,
                        room.id,
                        room.lastActivity,
                        date,
                    )
                    break
                progress.update(task, advance=1)
        logger.info("Total active rooms found: %d", len(active_rooms))
        return active_rooms

    def get_messages_for_rooms(
        self, rooms: list[Room], date: datetime, local_tz: tzinfo
    ) -> list[Message]:
        """Get all messages for the given rooms and date."""
        messages: list[Message] = []
        seen_message_ids: set[str] = set()  # Track seen message IDs
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Fetching messages from active rooms..."),
            TextColumn("[green]Processed: {task.completed}/{task.total}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "Fetching messages from rooms...", total=len(rooms)
            )
            logger.info("Fetching messages from %d active rooms", len(rooms))
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {
                    executor.submit(
                        get_messages,
                        self._client,
                        date,
                        self.config.user_email,
                        room,
                        local_tz,
                    ): room
                    for room in rooms
                }
                for future in as_completed(futures):
                    result: MessageAnalysisResult = future.result()
                    if result.messages:
                        for msg in result.messages:
                            # Only add if we haven't seen this message ID before
                            if msg.id not in seen_message_ids:
                                seen_message_ids.add(msg.id)
                                logger.debug(
                                    (
                                        "Message ID %s in room %s (ID %s) from sender "
                                        "%s at %s"
                                    ),
                                    msg.id,
                                    result.room.title,
                                    result.room.id,
                                    msg.sender.display_name,
                                    msg.timestamp,
                                )
                                messages.append(msg)
                            else:
                                logger.debug(
                                    "Skipping duplicate message ID %s",
                                    msg.id,
                                )
                    progress.update(task, advance=1)

        logger.info(f"Total messages aggregated: {len(messages)}")
        messages.sort(key=lambda x: x.timestamp)
        return messages

    def get_activity(
        self, date: datetime, local_tz: tzinfo, room_chunk_size: int = 50
    ) -> list[Message]:
        """Get all activity for the specified date as a list of Message objects."""
        active_rooms = self.get_rooms_active_since_date(date)
        logger.info(
            "A total of %d active rooms were found on date %s", len(active_rooms), date
        )
        messages = self.get_messages_for_rooms(active_rooms, date, local_tz)
        logger.info("A total of %d messages were found on date %s", len(messages), date)
        messages.sort(key=lambda x: x.timestamp)
        return messages


def parse_message_time(sdk_message: SDKMessage, local_tz: tzinfo) -> datetime:
    """Parse the message creation time to local timezone."""
    message_time = datetime.strptime(str(sdk_message.created), "%Y-%m-%dT%H:%M:%S.%fZ")
    message_time = message_time.replace(tzinfo=UTC).astimezone(local_tz)
    return message_time


def create_message(
    sdk_message: SDKMessage, client: WebexAPI, room: Room, local_tz: tzinfo
) -> Message:
    """Create a Message object from an SDKMessage."""
    sdk_sender = client.people.get(sdk_message.personId)
    sender = sdk_person_to_user(sdk_sender)
    recipients: list[User] = []  # Not available from SDK directly
    message_time = parse_message_time(sdk_message, local_tz)
    return Message(
        id=sdk_message.id,
        space_id=room.id,
        space_type=get_space_type(room),
        space_name=room.title,
        sender=sender,
        recipients=recipients,
        timestamp=message_time,
        content=sdk_message.text or "",
    )


def build_analysis_result(
    room: Room,
    all_messages: list[Message],
    last_activity: datetime | None,
    had_activity_on_or_after_date: bool,
    user_sent: bool,
) -> MessageAnalysisResult:
    """Build the MessageAnalysisResult based on whether the user sent a message."""
    if user_sent:
        return MessageAnalysisResult(
            room=room,
            messages=all_messages,
            last_activity=last_activity,
            had_activity_on_or_after_date=had_activity_on_or_after_date,
        )
    else:
        return MessageAnalysisResult(
            room=room,
            messages=[],
            last_activity=last_activity,
            had_activity_on_or_after_date=had_activity_on_or_after_date,
        )


def get_messages(
    client: WebexAPI, date: datetime, user_email: str, room: Room, local_tz: tzinfo
) -> MessageAnalysisResult:
    """Get all messages for a specific date in a room.

    Only returns messages if the user sent at least one message in that room on that
    date.
    """
    all_messages: list[Message] = []
    user_sent = False
    had_activity_on_or_after_date = False

    messages: Generator[SDKMessage, None, None] = client.messages.list(roomId=room.id)
    last_activity: datetime | None = None

    for sdk_message in messages:
        if sdk_message.created is None:
            logger.warning(
                "Message %s has no creation date, skipping...", sdk_message.id
            )
            continue

        message_time = parse_message_time(sdk_message, local_tz)
        if last_activity is None or message_time > last_activity:
            last_activity = message_time

        if message_time.date() == date.date():
            msg = create_message(sdk_message, client, room, local_tz)
            logger.debug(
                "Processing SDK message %s from email %s created at %s",
                sdk_message.id,
                sdk_message.personEmail,
                sdk_message.created,
            )
            all_messages.append(msg)
            if sdk_message.personEmail == user_email:
                logger.debug(
                    "Authenticated user (%s == %s) sent message %s",
                    sdk_message.personEmail,
                    user_email,
                    sdk_message.id,
                )
                user_sent = True

        if message_time.date() >= date.date():
            had_activity_on_or_after_date = True
        elif message_time.date() < date.date():
            logger.debug(
                "Message %s from email %s is before the target date %s, "
                "stopping processing...",
                sdk_message.id,
                sdk_message.personEmail,
                date,
            )
            break

    return build_analysis_result(
        room,
        all_messages,
        last_activity,
        had_activity_on_or_after_date,
        user_sent,
    )
