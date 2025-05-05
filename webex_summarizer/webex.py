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
from webexpythonsdk.models.immutable import Message, Person, Room

from .config import AppConfig
from .types import MessageData

# Initialize Rich console
console = Console()


class WebexClient:
    """Wrapper around Webex API client."""

    def __init__(self, config: AppConfig, client: WebexAPI | None = None) -> None:
        """Initialize with configuration."""
        self.config = config
        self._client = client or WebexAPI(access_token=config.webex_token)
        self._me: Person | None = None

    def get_me(self) -> Person:
        """Get user information."""
        if not self._me:
            self._me = self._client.people.me()
        return self._me

    def get_activity(self, date: datetime, local_tz: tzinfo) -> list[MessageData]:
        """Get all activity for the specified date."""
        rooms = get_rooms_with_activity(self._client, date, local_tz)

        message_data = []
        for room in rooms:
            messages = get_messages(
                self._client, date, self.config.user_email, room, local_tz
            )
            message_data.extend(messages)

        message_data.sort(key=lambda x: x["time"])
        return message_data


def get_message_time(message: Message, local_tz: tzinfo) -> datetime:
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
            messages: Generator[Message, None, None] = client.messages.list(
                roomId=room.id, max=100
            )

            first_message_slice_obj = slice(0, 1)
            first_message_slice = messages[first_message_slice_obj]  # type: ignore
            first_message = next(first_message_slice, None)
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
) -> list[MessageData]:
    """Get messages sent by user on a specific date."""
    filtered_messages: list[MessageData] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"Fetching messages from [cyan]{room.title}[/]", total=None
        )

        messages: Generator[Message, None, None] = client.messages.list(
            roomId=room.id, max=100
        )

        for message in messages:
            if message.created is None:
                continue

            message_time = get_message_time(message, local_tz)
            if message_time.date() == date.date():
                if message.personEmail == user_email:
                    room = client.rooms.get(message.roomId)
                    filtered_messages.append(
                        {
                            "time": message_time,
                            "space": room.title,
                            "text": message.text,
                        }
                    )
            elif message_time.date() < date.date():
                console.log(
                    f"Found [bold]{len(filtered_messages)}[/] relevant messages in "
                    f"[cyan]{room.title}[/]"
                )
                break

        progress.update(task, completed=1.0)

    return filtered_messages
