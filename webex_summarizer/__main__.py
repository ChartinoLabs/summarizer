"""Summarize messages sent by a user during a period of time and GitHub commits."""

import getpass
import os
from datetime import datetime, timezone

from dotenv import load_dotenv
from rich.prompt import Prompt
from webexpythonsdk import WebexAPI

from .console_ui import console, display_results, display_welcome_panel
from .github_utils import authenticate_github, get_github_commits
from .webex import get_messages, get_rooms_with_activity


def main() -> None:
    # Load environment variables from .env file
    load_dotenv()

    display_welcome_panel()

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

    message_data = []
    for room in rooms:
        messages = get_messages(webex_client, date, user_email, room, local_tz)
        message_data.extend(messages)

    message_data.sort(key=lambda x: x["time"])

    commit_data = get_github_commits(
        github_api, date, local_tz
    )
    commit_data.sort(key=lambda x: x["time"])

    display_results(message_data, commit_data, me.displayName, str(date.date()))


if __name__ == "__main__":
    main()
