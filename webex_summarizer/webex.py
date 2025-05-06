"""Webex API interaction functions."""

from collections.abc import Generator
from datetime import UTC, datetime, tzinfo

from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from webexpythonsdk import WebexAPI
from webexpythonsdk.models.immutable import Message as SDKMessage, Person, Room

from .config import AppConfig
from .models import Message, SpaceType, User

# Initialize Rich console
console = Console()


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

    def get_activity(self, date: datetime, local_tz: tzinfo) -> list[Message]:
        """Get all activity for the specified date as a list of Message objects."""
        rooms = get_rooms_with_activity(self._client, date, local_tz)

        messages: list[Message] = []
        for room in rooms:
            room_messages = get_messages(
                self._client, date, self.config.user_email, room, local_tz
            )
            messages.extend(room_messages)

        messages.sort(key=lambda x: x.timestamp)
        return messages


def get_message_time(message: SDKMessage, local_tz: tzinfo) -> datetime:
    """Get message time in local timezone."""
    message_time = datetime.strptime(str(message.created), "%Y-%m-%dT%H:%M:%S.%fZ")
    message_time = message_time.replace(tzinfo=UTC).astimezone(local_tz)
    return message_time


def get_rooms_with_activity(
    client: WebexAPI, desired_date: datetime, local_tz: tzinfo
) -> list[Room]:
    """Get rooms user is a member of with recent activity within date."""
    rooms_with_activity: list[Room] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        fetch_task = progress.add_task("Fetching rooms...", total=None)
        rooms: Generator[Room, None, None] = client.rooms.list(
            max=250, sortBy="lastactivity"
        )
        progress.update(
            fetch_task, description="Processing rooms", total=1.0, completed=0.5
        )

        for room in rooms:
            progress.update(fetch_task, description=f"Checking room: {room.title}")
            messages: Generator[SDKMessage, None, None] = client.messages.list(
                roomId=room.id, max=100
            )

            first_message_slice_obj = slice(0, 1)
            first_message_slice: Generator[SDKMessage, None, None] = messages[  # type: ignore
                first_message_slice_obj
            ]
            first_message = next(first_message_slice, None)  # type: ignore
            if first_message is None:
                console.log(f"No messages found in room: [yellow]{room.title}[/]")
                continue

            if first_message.created is None:
                console.log(
                    f"First message in room [yellow]{room.title}[/] has no creation "
                    "time."
                )
                continue

            first_message_time = get_message_time(first_message, local_tz)
            if first_message_time.date() < desired_date.date():
                console.log(
                    f"First message in room [yellow]{room.title}[/] is older than the "
                    "date we are looking for."
                )
                break
            elif first_message_time.date() == desired_date.date():
                console.log(
                    f"First message in room [green]{room.title}[/] indicates activity"
                )
                rooms_with_activity.append(room)
                continue

            for message in messages:
                if message.created is None:
                    continue
                message_time = get_message_time(message, local_tz)
                if message_time.date() == desired_date.date():
                    console.log(
                        f"Recent activity found in room: [green]{room.title}[/]"
                    )
                    console.log(
                        f"[{message_time.strftime('%m-%d %H:%M:%S')}] "
                        f"([cyan]{room.title}[/]) {message.text}"
                    )
                    rooms_with_activity.append(room)
                    break
                if message_time.date() < desired_date.date():
                    break

        progress.update(fetch_task, completed=1.0)

    return rooms_with_activity


def get_messages(
    client: WebexAPI, date: datetime, user_email: str, room: Room, local_tz: tzinfo
) -> list[Message]:
    """Get messages sent by user on a specific date as Message dataclasses."""
    filtered_messages: list[Message] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"Fetching messages from [cyan]{room.title}[/]", total=None
        )

        messages: Generator[SDKMessage, None, None] = client.messages.list(
            roomId=room.id, max=100
        )

        for sdk_message in messages:
            if sdk_message.created is None:
                continue

            message_time = get_message_time(sdk_message, local_tz)
            if message_time.date() == date.date():
                if sdk_message.personEmail == user_email:
                    # Get sender details from Webex API
                    sdk_sender = client.people.get(sdk_message.personId)
                    sender = sdk_person_to_user(sdk_sender)
                    recipients: list[User] = []  # Not available from SDK directly
                    filtered_messages.append(
                        Message(
                            id=sdk_message.id,
                            space_id=room.id,
                            space_type=get_space_type(room),
                            space_name=room.title,
                            sender=sender,
                            recipients=recipients,
                            timestamp=message_time,
                            content=sdk_message.text or "",
                        )
                    )
            elif message_time.date() < date.date():
                console.log(
                    f"Found [bold]{len(filtered_messages)}[/] relevant messages in "
                    f"[cyan]{room.title}[/]"
                )
                break

        progress.update(task, completed=1.0)

    return filtered_messages
