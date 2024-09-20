"""Summarize messages sent by a user during a period of time."""

import getpass
from datetime import datetime, timezone, tzinfo
from typing import Generator, TypedDict

from webexteamssdk import WebexTeamsAPI
from webexteamssdk.models.immutable import Message, Room
from webexteamssdk.generator_containers import GeneratorContainer


class MessageData(TypedDict):
    """Message data structure."""

    time: datetime
    space: str
    text: str


def get_message_time(message: Message, local_tz: tzinfo) -> datetime:
    """Get message time in local timezone."""
    message_time = datetime.strptime(str(message.created), "%Y-%m-%dT%H:%M:%S.%fZ")
    message_time = message_time.replace(tzinfo=timezone.utc).astimezone(local_tz)
    return message_time


def get_rooms_with_activity(
    api: WebexTeamsAPI, desired_date: datetime, local_tz: tzinfo
) -> list[Room]:
    """Get rooms user is a member of with recent activity within date."""
    print("Fetching rooms...")
    rooms: Generator[Room, None, None] = api.rooms.list(max=250, sortBy="lastactivity")
    print(f"Finished fetching rooms.")
    rooms_with_activity: list[Room] = []
    for room in rooms:
        print(f"Fetching messages from room: {room.title}")
        messages: Generator[Message, None, None] = api.messages.list(
            roomId=room.id, max=100
        )
        print(f"Finished fetching messages from room: {room.title}")

        # This is odd, but WebexPythonSDK doesn't return a generator, it
        # returns a GeneratorContainer, which is a wrapper around the
        # generator. This means we can't extract the first message
        # directly from the generator via the next() built-in function, but
        # we can slice the first message from the generator container.
        #
        # This is super odd, but it's how the SDK was designed, much to my
        # dismay.
        first_message_slice_obj = slice(0, 1)
        first_message_slice = messages[first_message_slice_obj]
        first_message = next(first_message_slice, None)
        if first_message is None:
            print(f"No messages found in room: {room.title}")
            continue

        if first_message.created is None:
            print(f"First message in room {room.title} has no creation time.")
            continue

        first_message_time = get_message_time(first_message, local_tz)
        if first_message_time.date() < desired_date.date():
            # If the first message in the room is older than the date we are
            # looking for, we can skip analyzing any further rooms, since they
            # are sorted by last activity.
            print(
                f"First message in room {room.title} is older than the date we are looking for."
            )
            break
        elif first_message_time.date() == desired_date.date():
            print(f"First message in room {room.title} indicates activity")
            rooms_with_activity.append(room)
            continue

        # Check if any other messages in the room are from the date we are
        # looking for.
        for message in messages:
            # print(f"Analyzing message from room {room.title}: {message}")
            if message.created is None:
                continue
            message_time = datetime.strptime(
                str(message.created), "%Y-%m-%dT%H:%M:%S.%fZ"
            )
            # print(f"Message time: {message_time}")
            message_time = message_time.replace(tzinfo=timezone.utc).astimezone(
                local_tz
            )
            # print(f"Message time in local timezone: {message_time}")
            # print(f"Message date: {message_time.date()}")
            if message_time.date() == desired_date.date():
                print(f"Recent activity found in room: {room.title}")
                print(
                    f"[{message_time.strftime('%m-%d %H:%M:%S')}] ({room.title}) "
                    f"{message.text}"
                )
                rooms_with_activity.append(room)
                break
            if message_time.date() < desired_date.date():
                # Since messages are returned in descending order of time, if
                # we reach a message that is older than the date we are
                # looking for, we can stop analyzing this room.
                break

    return rooms_with_activity


def get_messages(
    api: WebexTeamsAPI, date: datetime, user_email: str, room: Room, local_tz: tzinfo
) -> list[MessageData]:
    """Get messages sent by user on a specific date."""
    print(f"Fetching messages from room: {room.title}")
    messages: Generator[Message, None, None] = api.messages.list(
        roomId=room.id, max=100
    )
    filtered_messages: list[MessageData] = []
    for message in messages:
        if message.created is None:
            continue

        message_time = datetime.strptime(str(message.created), "%Y-%m-%dT%H:%M:%S.%fZ")
        message_time = message_time.replace(tzinfo=timezone.utc).astimezone(local_tz)
        if message_time.date() == date.date():
            if message.personEmail == user_email:
                room = api.rooms.get(message.roomId)
                filtered_messages.append(
                    {"time": message_time, "space": room.title, "text": message.text}
                )
        elif message_time.date() < date.date():
            # Messages are returned in descending order of time, so if we reach
            # a message that is older than the date we are looking for, we can
            # stop analyzing this room.
            print(
                "Found the end of messages for the date we are looking for "
                f"- {len(filtered_messages)} relevant messages found."
            )
            break
    return filtered_messages


# Main function
def main() -> None:
    user_email = input("Enter your Cisco email: ")
    print("Enter your access token by fetching it from the link below:")
    print("https://developer.webex.com/docs/getting-started")
    access_token = getpass.getpass("Enter your Webex access token: ")
    date_str = input("Enter the date (YYYY-MM-DD): ")
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        print("Invalid date format. Please enter the date in YYYY-MM-DD format.")
        return

    # Identify local timezone via locale
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is None:
        print("Unable to identify local timezone. Defaulting to UTC.")
        local_tz = timezone.utc

    api = WebexTeamsAPI(access_token=access_token)

    # Confirm API access works by fetching the user's details
    me = api.people.me()

    print(f"Identifying rooms with activity on {date.date()}...")

    rooms = get_rooms_with_activity(api, date, local_tz)

    print(f"Identified {len(rooms)} rooms with activity on {date}.")

    message_data: list[MessageData] = []
    for room in rooms:
        messages = get_messages(api, date, user_email, room, local_tz)
        message_data.extend(messages)

    # Sort messages by time from earliest to latest
    message_data.sort(key=lambda x: x["time"])

    print(
        f"Identified {len(message_data)} messages sent by {me.displayName} "
        f"on {date}:"
    )
    print()
    for message in message_data:
        # One line per message
        print(
            f"[{message['time'].strftime('%m-%d %H:%M:%S')}] ({message['space']}) "
            f"{message['text']}"
        )


if __name__ == "__main__":
    main()
