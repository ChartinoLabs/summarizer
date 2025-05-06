"""Console UI components for webex-summarizer."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models import Message, SpaceType

console = Console()


def display_welcome_panel() -> None:
    """Display welcome panel."""
    console.print(
        Panel.fit(
            "[bold blue]Webex & GitHub Activity Summarizer[/]",
            subtitle="Summarize your messages and commits",
        )
    )


def display_results(messages: list[Message], user_name: str, date_str: str) -> None:
    """Display the results as tables."""
    console.print(
        f"\nFound [bold green]{len(messages)}[/] messages by "
        f"[bold]{user_name}[/] on {date_str}:"
    )

    if messages:
        console.print("\n[bold]Webex Messages:[/]")
        table = Table(show_header=True)
        table.add_column("Time", style="cyan")
        table.add_column("Sender", style="green")
        table.add_column("Space", style="green")
        table.add_column("Message", style="white", no_wrap=False, overflow="fold")

        for message in messages:
            if message.space_type == SpaceType.DM:
                space_name = "DM"
            else:
                space_name = message.space_id

            table.add_row(
                message.timestamp.strftime("%H:%M:%S"),
                message.sender.display_name,
                space_name,
                message.content,
            )

        console.print(table)

    if not messages:
        console.print("[yellow]No activity found for this date.[/]")
