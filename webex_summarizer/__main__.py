"""Summarize messages sent by a user during a period of time and GitHub commits."""

import os
import getpass
from datetime import datetime, timezone, tzinfo
from typing import Generator, TypedDict, List
from dotenv import load_dotenv

from webexpythonsdk import WebexAPI
from webexpythonsdk.models.immutable import Room, Message
from github import Github
from github.GithubException import GithubException
from github.Commit import Commit


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


ORGANIZATIONS_TO_IGNORE = [
    "AS-Community",
    "besaccess",
    "cx-usps-auto",
    "SVS-DELIVERY",
    "pyATS",
    "netascode",
    "CX-CATL",
]


def get_message_time(message: Message, local_tz: tzinfo) -> datetime:
    """Get message time in local timezone."""
    message_time = datetime.strptime(str(message.created), "%Y-%m-%dT%H:%M:%S.%fZ")
    message_time = message_time.replace(tzinfo=timezone.utc).astimezone(local_tz)
    return message_time


def get_rooms_with_activity(
    client: WebexAPI, desired_date: datetime, local_tz: tzinfo
) -> list[Room]:
    """Get rooms user is a member of with recent activity within date."""
    print("Fetching rooms...")
    rooms: Generator[Room, None, None] = client.rooms.list(
        max=250, sortBy="lastactivity"
    )
    print(f"Finished fetching rooms.")
    rooms_with_activity: list[Room] = []
    for room in rooms:
        print(f"Fetching messages from room: {room.title}")
        messages: Generator[Message, None, None] = client.messages.list(
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
        first_message_slice = messages[first_message_slice_obj]  # type: ignore
        first_message = next(first_message_slice, None)
        if first_message is None:
            print(f"No messages found in room: {room.title}")
            continue

        if first_message.created is None:
            print(f"First message in room {room.title} has no creation time.")
            continue

        first_message_time = get_message_time(first_message, local_tz)
        if first_message_time.date() < desired_date.date():
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
            if message.created is None:
                continue
            message_time = get_message_time(message, local_tz)
            if message_time.date() == desired_date.date():
                print(f"Recent activity found in room: {room.title}")
                print(
                    f"[{message_time.strftime('%m-%d %H:%M:%S')}] ({room.title}) "
                    f"{message.text}"
                )
                rooms_with_activity.append(room)
                break
            if message_time.date() < desired_date.date():
                break

    return rooms_with_activity


def get_messages(
    client: WebexAPI, date: datetime, user_email: str, room: Room, local_tz: tzinfo
) -> list[MessageData]:
    """Get messages sent by user on a specific date."""
    print(f"Fetching messages from room: {room.title}")
    messages: Generator[Message, None, None] = client.messages.list(
        roomId=room.id, max=100
    )
    filtered_messages: list[MessageData] = []
    for message in messages:
        if message.created is None:
            continue

        message_time = get_message_time(message, local_tz)
        if message_time.date() == date.date():
            if message.personEmail == user_email:
                room = client.rooms.get(message.roomId)
                filtered_messages.append(
                    {"time": message_time, "space": room.title, "text": message.text}
                )
        elif message_time.date() < date.date():
            print(
                "Found the end of messages for the date we are looking for "
                f"- {len(filtered_messages)} relevant messages found."
            )
            break
    return filtered_messages


def authenticate_github(token: str, base_url: str) -> Github:
    """Authenticate with GitHub Enterprise."""
    return Github(base_url=base_url, login_or_token=token)


def get_github_commits(
    gh: Github,
    date: datetime,
    local_tz: tzinfo,
    organizations_to_ignore: list[str] = [],
) -> List[CommitData]:
    """Get commits made by the authenticated user on a specific date."""
    commits: List[CommitData] = []
    for repo in gh.get_user().get_repos():
        if repo.owner.login in organizations_to_ignore:
            # print(
            #     f"Skipping repository: {repo.name} in organization: {repo.owner.login}"
            # )
            continue
        else:
            print(
                f"Fetching commits from repository: {repo.name} in organization: {repo.owner.login}"
            )
        try:
            for commit in repo.get_commits(author=gh.get_user().login):
                commit_time = commit.commit.author.date.replace(
                    tzinfo=timezone.utc
                ).astimezone(local_tz)
                if commit_time.date() == date.date():
                    commits.append(
                        {
                            "time": commit_time,
                            "repo": repo.name,
                            "message": commit.commit.message,
                            "sha": commit.sha,
                        }
                    )
                elif commit_time.date() < date.date():
                    break
        except GithubException as e:
            print(f"Error fetching commits from {repo.name}: {e}")

    return commits


# Main function
def main() -> None:
    # Load environment variables from .env file
    load_dotenv()

    user_email = input("Enter your Cisco email: ")
    print("Enter your Webex access token by fetching it from the link below:")
    print("https://developer.webex.com/docs/getting-started")
    webex_token = getpass.getpass("Enter your Webex access token: ")

    # Try to get GitHub PAT from .env file first
    github_token = os.getenv("GITHUB_PAT")
    if not github_token:
        print("GitHub PAT not found in .env file.")
        github_token = getpass.getpass("Enter your GitHub Enterprise PAT: ")

    # Select the GitHub Enterprise instance to use from a list of known
    # instances
    known_github_instances = [
        "https://github.com/api/v3",
        "https://wwwin-github.cisco.com/api/v3",
    ]

    # Try to get GitHub base URL from .env file first
    github_base_url = os.getenv("GITHUB_BASE_URL")
    if not github_base_url:
        # Display known GitHub Enterprise instances to user
        print("Known GitHub Enterprise instances:")
        for i, instance in enumerate(known_github_instances, start=1):
            print(f"  {i}: {instance}")
        selection = int(
            input(
                "Enter the number of the GitHub Enterprise instance you want to use: "
            )
        )
        github_base_url = known_github_instances[selection - 1]
    else:
        print(f"Using GitHub base URL from .env file: {github_base_url}")

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

    webex_client = WebexAPI(access_token=webex_token)
    github_api = authenticate_github(github_token, github_base_url)

    # Confirm API access works by fetching the user's details
    me = webex_client.people.me()

    print(f"Identifying rooms with activity and GitHub commits on {date.date()}...")

    rooms = get_rooms_with_activity(webex_client, date, local_tz)
    print(f"Identified {len(rooms)} rooms with activity on {date}.")

    message_data: list[MessageData] = []
    for room in rooms:
        messages = get_messages(webex_client, date, user_email, room, local_tz)
        message_data.extend(messages)

    # Sort messages by time from earliest to latest
    message_data.sort(key=lambda x: x["time"])

    commit_data = get_github_commits(
        github_api, date, local_tz, ORGANIZATIONS_TO_IGNORE
    )
    commit_data.sort(key=lambda x: x["time"])

    print(
        f"Identified {len(message_data)} messages and {len(commit_data)} commits sent by {me.displayName} on {date}:"
    )
    print("\nWebex Messages:")
    for message in message_data:
        print(
            f"[{message['time'].strftime('%m-%d %H:%M:%S')}] ({message['space']}) "
            f"{message['text']}"
        )

    print("\nGitHub Commits:")
    for commit in commit_data:
        print(
            f"[{commit['time'].strftime('%m-%d %H:%M:%S')}] ({commit['repo']}) "
            f"{commit['message']} (SHA: {commit['sha'][:7]})"
        )


if __name__ == "__main__":
    main()
