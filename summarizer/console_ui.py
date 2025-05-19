"""Console UI components for webex-summarizer."""

from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from .models import Conversation

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
    message_data: list[dict[str, object]], user_name: str, date_str: str
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
            msg: dict[str, object] = message
            time_val = msg.get("time", "-")
            if isinstance(time_val, datetime):
                time_str = time_val.strftime("%H:%M:%S")
            else:
                time_str = "-"
            table.add_row(
                time_str,
                str(msg.get("space", "-")),
                str(msg.get("text", "-")),
            )

        console.print(table)

    if not message_data:
        console.print("[yellow]No activity found for this date.[/]")


def display_conversations(
    conversations: list[Conversation],
    time_display_format: str = "12h",
) -> None:
    """Display each conversation as a table with a header of stats."""
    if not conversations:
        console.print("[yellow]No conversations found.[/]")
        return

    for convo in conversations:
        # Header with stats
        start_fmt = _format_time(convo.start_time, time_display_format)
        end_fmt = _format_time(convo.end_time, time_display_format)
        participants = ", ".join([u.display_name for u in convo.participants])
        duration = (
            f"{convo.duration_seconds // 60} min {convo.duration_seconds % 60} sec"
            if convo.duration_seconds is not None
            else "-"
        )
        header = (
            f"[bold]Conversation {convo.id}[/] | "
            f"[cyan]{len(convo.messages)} messages[/] | "
            f"[magenta]Participants:[/] {participants} | "
            f"[green]Start:[/] {start_fmt} | [green]End:[/] {end_fmt} | "
            f"[yellow]Duration:[/] {duration} | "
            f"[blue]{'Threaded' if convo.is_threaded else 'Non-threaded'}[/]"
        )
        console.print(Panel(header, style="bold white"))

        # Table of messages
        table = Table(show_header=True)
        table.add_column("Time", style="cyan")
        table.add_column("Sender", style="green")
        table.add_column("Message", style="white", no_wrap=False, overflow="fold")
        for msg in convo.messages:
            table.add_row(
                _format_time(msg.timestamp, time_display_format),
                msg.sender.display_name,
                msg.content,
            )
        console.print(table)
        console.print()  # Blank line between conversations


def _format_time(dt: datetime | None, fmt: str) -> str:
    if not dt:
        return "-"
    if fmt == "24h":
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        return dt.strftime("%Y-%m-%d %I:%M:%S %p")
