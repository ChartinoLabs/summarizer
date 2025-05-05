"""Console UI components for webex-summarizer."""

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .types import MessageData

console = Console()


def display_welcome_panel() -> None:
    """Display welcome panel."""
    console.print(
        Panel.fit(
            "[bold blue]Webex & GitHub Activity Summarizer[/]",
            subtitle="Summarize your messages and commits",
        )
    )


def display_results(
    message_data: list[MessageData], user_name: str, date_str: str
) -> None:
    """Display the results as tables."""
    console.print(
        f"\nFound [bold green]{len(message_data)}[/] messages by "
        f"[bold]{user_name}[/] on {date_str}:"
    )

    if message_data:
        console.print("\n[bold]Webex Messages:[/]")
        table = Table(show_header=True)
        table.add_column("Time", style="cyan")
        table.add_column("Space", style="green")
        table.add_column("Message", style="white", no_wrap=False, overflow="fold")

        for message in message_data:
            table.add_row(
                message["time"].strftime("%H:%M:%S"), message["space"], message["text"]
            )

        console.print(table)

    if not message_data:
        console.print("[yellow]No activity found for this date.[/]")
