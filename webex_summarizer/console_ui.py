"""Console UI components for webex-summarizer."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .types import CommitData, MessageData

console = Console()


def display_welcome_panel():
    """Display welcome panel."""
    console.print(Panel.fit(
        "[bold blue]Webex & GitHub Activity Summarizer[/]", 
        subtitle="Summarize your messages and commits"
    ))


def display_results(message_data: list[MessageData], commit_data: list[CommitData], user_name: str, date_str: str):
    """Display the results as tables."""
    console.print(
        f"\nFound [bold green]{len(message_data)}[/] messages and [bold green]{len(commit_data)}[/] "
        f"commits by [bold]{user_name}[/] on {date_str}:"
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
