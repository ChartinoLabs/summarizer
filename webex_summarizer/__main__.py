"""Summarize messages sent by a user during a period of time and GitHub commits."""

import getpass
import os
from datetime import datetime, timezone, tzinfo
from typing import Generator, List, TypedDict

from dotenv import load_dotenv
from github import Github
from github.GithubException import GithubException
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.prompt import Prompt
from rich.table import Table
from webexpythonsdk import WebexAPI
from webexpythonsdk.models.immutable import Message, Room


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

# Initialize Rich console
console = Console()


def get_message_time(message: Message, local_tz: tzinfo) -> datetime:
    """Get message time in local timezone."""
    message_time = datetime.strptime(str(message.created), "%Y-%m-%dT%H:%M:%S.%fZ")
    message_time = message_time.replace(tzinfo=timezone.utc).astimezone(local_tz)
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
        console=console
    ) as progress:
        fetch_task = progress.add_task("Fetching rooms...", total=None)
        rooms: Generator[Room, None, None] = client.rooms.list(
            max=250, sortBy="lastactivity"
        )
        progress.update(fetch_task, description="Processing rooms", total=1.0, completed=0.5)

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
                console.log(f"First message in room [yellow]{room.title}[/] has no creation time.")
                continue

            first_message_time = get_message_time(first_message, local_tz)
            if first_message_time.date() < desired_date.date():
                console.log(
                    f"First message in room [yellow]{room.title}[/] is older than the date we are looking for."
                )
                break
            elif first_message_time.date() == desired_date.date():
                console.log(f"First message in room [green]{room.title}[/] indicates activity")
                rooms_with_activity.append(room)
                continue

            for message in messages:
                if message.created is None:
                    continue
                message_time = get_message_time(message, local_tz)
                if message_time.date() == desired_date.date():
                    console.log(f"Recent activity found in room: [green]{room.title}[/]")
                    console.log(
                        f"[{message_time.strftime('%m-%d %H:%M:%S')}] ([cyan]{room.title}[/]) "
                        f"{message.text}"
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
        console=console
    ) as progress:
        task = progress.add_task(f"Fetching messages from [cyan]{room.title}[/]", total=None)

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
                        {"time": message_time, "space": room.title, "text": message.text}
                    )
            elif message_time.date() < date.date():
                console.log(
                    f"Found [bold]{len(filtered_messages)}[/] relevant messages in [cyan]{room.title}[/]"
                )
                break

        progress.update(task, completed=1.0)

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

    with Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        main_task = progress.add_task("Checking repositories...", total=None)

        for repo in gh.get_user().get_repos():
            if repo.owner.login in organizations_to_ignore:
                continue

            progress.update(main_task, description=f"Checking repo: [cyan]{repo.name}[/] ({repo.owner.login})")

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
                console.log(f"[red]Error fetching commits from {repo.name}: {e}[/]")

        progress.update(main_task, completed=1.0)

    return commits


# Main function
def main() -> None:
    # Load environment variables from .env file
    load_dotenv()

    console.print(Panel.fit(
        "[bold blue]Webex & GitHub Activity Summarizer[/]", 
        subtitle="Summarize your messages and commits"
    ))

    user_email = Prompt.ask("Enter your Cisco email")
    console.print("Enter your Webex access token by fetching it from the link below:")
    console.print("[link=https://developer.webex.com/docs/getting-started]https://developer.webex.com/docs/getting-started[/link]")
    webex_token = getpass.getpass("Enter your Webex access token: ")

    github_token = os.getenv("GITHUB_PAT")
    if not github_token:
        console.print("[yellow]GitHub PAT not found in .env file.[/]")
        github_token = getpass.getpass("Enter your GitHub Enterprise PAT: ")

    known_github_instances = [
        "https://github.com/api/v3",
        "https://wwwin-github.cisco.com/api/v3",
    ]

    github_base_url = os.getenv("GITHUB_BASE_URL")
    if not github_base_url:
        console.print("[bold]Known GitHub Enterprise instances:[/]")
        for i, instance in enumerate(known_github_instances, start=1):
            console.print(f"  {i}: [cyan]{instance}[/]")
        selection = int(
            Prompt.ask(
                "Enter the number of the GitHub Enterprise instance you want to use",
                choices=[str(i) for i in range(1, len(known_github_instances) + 1)]
            )
        )
        github_base_url = known_github_instances[selection - 1]
    else:
        console.print(f"Using GitHub base URL from .env file: [cyan]{github_base_url}[/]")

    date_str = Prompt.ask("Enter the date", default=datetime.now().strftime("%Y-%m-%d"))
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        console.print("[red]Invalid date format. Please enter the date in YYYY-MM-DD format.[/]")
        return

    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is None:
        console.print("[yellow]Unable to identify local timezone. Defaulting to UTC.[/]")
        local_tz = timezone.utc

    with console.status("[bold green]Connecting to APIs...[/]") as status:
        webex_client = WebexAPI(access_token=webex_token)
        github_api = authenticate_github(github_token, github_base_url)

        me = webex_client.people.me()
        console.log(f"Connected as [bold green]{me.displayName}[/]")

    console.print(f"Looking for activity on [bold]{date.date()}[/]...")

    rooms = get_rooms_with_activity(webex_client, date, local_tz)
    console.print(f"Identified [bold green]{len(rooms)}[/] rooms with activity on {date.date()}.")

    message_data: list[MessageData] = []
    for room in rooms:
        messages = get_messages(webex_client, date, user_email, room, local_tz)
        message_data.extend(messages)

    message_data.sort(key=lambda x: x["time"])

    commit_data = get_github_commits(
        github_api, date, local_tz, ORGANIZATIONS_TO_IGNORE
    )
    commit_data.sort(key=lambda x: x["time"])

    console.print(
        f"\nFound [bold green]{len(message_data)}[/] messages and [bold green]{len(commit_data)}[/] commits by [bold]{me.displayName}[/] on {date.date()}:"
    )

    if message_data:
        console.print("\n[bold]Webex Messages:[/]")
        table = Table(show_header=True)
        table.add_column("Time", style="cyan")
        table.add_column("Space", style="green")
        table.add_column("Message", style="white", no_wrap=False, overflow="fold")

        for message in message_data:
            table.add_row(
                message['time'].strftime('%H:%M:%S'),
                message['space'],
                message['text']
            )

        console.print(table)

    if commit_data:
        console.print("\n[bold]GitHub Commits:[/]")
        table = Table(show_header=True)
        table.add_column("Time", style="cyan")
        table.add_column("Repository", style="green")
        table.add_column("Message", style="white", no_wrap=False, overflow="fold")
        table.add_column("SHA", style="dim")

        for commit in commit_data:
            table.add_row(
                commit['time'].strftime('%H:%M:%S'),
                commit['repo'],
                commit['message'],
                commit['sha'][:7]
            )

        console.print(table)

    if not message_data and not commit_data:
        console.print("[yellow]No activity found for this date.[/]")


if __name__ == "__main__":
    main()
