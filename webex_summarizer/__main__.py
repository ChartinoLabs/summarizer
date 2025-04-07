"""Summarize messages sent by a user during a period of time and GitHub commits."""

import getpass
from datetime import datetime, timezone

from rich.prompt import Prompt

from .config import AppConfig, get_known_github_instances, load_config_from_env
from .console_ui import console, display_results, display_welcome_panel
from .github_utils import GitHubClient
from .webex import WebexClient


def get_user_config() -> AppConfig:
    """Get user configuration through prompts."""
    env_config = load_config_from_env()
    
    display_welcome_panel()

    user_email = Prompt.ask("Enter your Cisco email")
    console.print("Enter your Webex access token by fetching it from the link below:")
    console.print("[link=https://developer.webex.com/docs/getting-started]https://developer.webex.com/docs/getting-started[/link]")
    webex_token = getpass.getpass("Enter your Webex access token: ")

    github_token = env_config.get("github_token")
    if not github_token:
        console.print("[yellow]GitHub PAT not found in .env file.[/]")
        github_token = getpass.getpass("Enter your GitHub Enterprise PAT: ")

    known_github_instances = get_known_github_instances()
    github_base_url = env_config.get("github_base_url")
    
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
        raise ValueError("Invalid date format")

    return AppConfig(
        webex_token=webex_token,
        github_token=github_token,
        github_base_url=github_base_url,
        user_email=user_email,
        target_date=date,
    )


def run_app(config: AppConfig) -> None:
    """Run the application with the given configuration."""
    local_tz = datetime.now().astimezone().tzinfo
    if local_tz is None:
        console.print("[yellow]Unable to identify local timezone. Defaulting to UTC.[/]")
        local_tz = timezone.utc

    with console.status("[bold green]Connecting to APIs...[/]") as status:
        webex_client = WebexClient(config)
        github_client = GitHubClient(config)

        me = webex_client.get_me()
        console.log(f"Connected as [bold green]{me.displayName}[/]")

    console.print(f"Looking for activity on [bold]{config.target_date.date()}[/]...")

    message_data = webex_client.get_activity(config.target_date, local_tz)
    commit_data = github_client.get_commits(config.target_date, local_tz)
    
    display_results(
        message_data, 
        commit_data, 
        me.displayName, 
        str(config.target_date.date())
    )


def main() -> None:
    """Entry point for the application."""
    try:
        config = get_user_config()
        run_app(config)
    except KeyboardInterrupt:
        console.print("\n[yellow]Operation cancelled by user.[/]")
    except Exception as e:
        console.print(f"[bold red]Error: {str(e)}[/]")


if __name__ == "__main__":
    main()
