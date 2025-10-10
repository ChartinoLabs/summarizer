"""Console UI components for webex-summarizer."""

from collections import Counter
from datetime import datetime, timedelta

import humanize
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from summarizer.common.models import Change, Conversation

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

    # Sort conversations by start time (earliest to latest)
    sorted_conversations = sorted(
        conversations, key=lambda conv: conv.start_time or datetime.min
    )

    for convo in sorted_conversations:
        # Header with stats
        start_fmt = _format_datetime(convo.start_time, time_display_format)
        end_fmt = _format_datetime(convo.end_time, time_display_format)
        participants = ", ".join([u.display_name for u in convo.participants])
        duration = (
            humanize.precisedelta(
                timedelta(seconds=convo.duration_seconds), minimum_unit="seconds"
            )
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
        table.add_column("Date & Time", style="cyan")
        table.add_column("Sender", style="green")
        table.add_column("Message", style="white", no_wrap=False, overflow="fold")
        for msg in convo.messages:
            table.add_row(
                _format_datetime(msg.timestamp, time_display_format),
                msg.sender.display_name,
                msg.content,
            )
        console.print(table)
        console.print()  # Blank line between conversations


def display_conversations_summary(
    conversations: list[Conversation],
    time_display_format: str = "12h",
) -> None:
    """Display a summary table of all conversations."""
    if not conversations:
        return

    console.print("\n" + "=" * 80)
    console.print("[bold cyan]Daily Conversation Summary[/]")
    console.print("=" * 80)

    # Sort conversations by start time (earliest to latest)
    sorted_conversations = sorted(
        conversations, key=lambda conv: conv.start_time or datetime.min
    )

    # Create summary table
    table = Table(show_header=True, title="Conversation Overview")
    table.add_column("Conversation ID", style="bold blue", no_wrap=True)
    table.add_column("Participants", style="green", no_wrap=False)
    table.add_column("Start Date & Time", style="cyan", no_wrap=True)
    table.add_column("End Date & Time", style="cyan", no_wrap=True)
    table.add_column("Duration", style="yellow", no_wrap=True)

    for convo in sorted_conversations:
        # Format participants as comma-separated list
        participants = ", ".join([u.display_name for u in convo.participants])

        # Format times with dates
        start_time = _format_datetime(convo.start_time, time_display_format)
        end_time = _format_datetime(convo.end_time, time_display_format)

        # Format duration using humanize with precision
        if convo.duration_seconds is not None:
            duration = humanize.precisedelta(
                timedelta(seconds=convo.duration_seconds), minimum_unit="seconds"
            )
        else:
            duration = "-"

        table.add_row(
            convo.id,
            participants,
            start_time,
            end_time,
            duration,
        )

    console.print(table)

    # Display summary statistics
    total_conversations = len(conversations)
    total_duration_seconds = sum(
        convo.duration_seconds
        for convo in conversations
        if convo.duration_seconds is not None
    )

    # Use humanize for total duration formatting with precision
    if total_duration_seconds > 0:
        duration_summary = humanize.precisedelta(
            timedelta(seconds=total_duration_seconds), minimum_unit="seconds"
        )
    else:
        duration_summary = "0 seconds"

    console.print("\n[bold]Summary Statistics:[/]")
    console.print(f"Total conversations: [bold green]{total_conversations}[/]")
    console.print(f"Total conversation time: [bold yellow]{duration_summary}[/]")


def _format_time(dt: datetime | None, fmt: str) -> str:
    if not dt:
        return "-"
    if fmt == "24h":
        return dt.strftime("%H:%M:%S")
    else:
        return dt.strftime("%I:%M:%S %p")


def _format_datetime(dt: datetime | None, fmt: str) -> str:
    """Format datetime with both date and time information."""
    if not dt:
        return "-"
    if fmt == "24h":
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    else:
        return dt.strftime("%Y-%m-%d %I:%M:%S %p")


# For the range of dates, print a header with each date
# in the range for ease of use/viewing.
def print_date_header(date: datetime) -> None:
    """Print a visually distinct header for a date using box-drawing characters."""
    date_str = date.strftime("%Y-%m-%d")
    header_text = f" {date_str} — Messages "
    width = max(60, len(header_text) + 8)
    top = f"╔{'═' * (width - 2)}╗"
    mid = f"║{header_text.center(width - 2)}║"
    bot = f"╚{'═' * (width - 2)}╝"
    console.print("\n" + top, style="bold blue")
    console.print(mid, style="bold white")
    console.print(bot, style="bold blue")


# =============================
# GitHub Changes UI components
# =============================


def display_changes(
    changes: list[Change],
    time_display_format: str = "12h",
) -> None:
    """Display a list of GitHub changes as a table."""
    if not changes:
        console.print("[yellow]No GitHub changes found.[/]")
        return

    # Sort by timestamp
    sorted_changes = sorted(changes, key=lambda ch: ch.timestamp)

    table = Table(show_header=True, title="GitHub Changes")
    table.add_column("Time", style="cyan", no_wrap=True)
    table.add_column("Type", style="magenta", no_wrap=True)
    table.add_column("Repo", style="green", no_wrap=True)
    table.add_column("Title", style="white", no_wrap=False, overflow="fold")

    for ch in sorted_changes:
        time_str = _format_time(ch.timestamp, time_display_format)
        table.add_row(time_str, ch.type.value, ch.repo_full_name, ch.title)

    console.print(table)


def display_changes_summary(changes: list[Change]) -> None:
    """Display a summary of GitHub changes by type and by repository."""
    if not changes:
        return

    console.print("\n" + "=" * 80)
    console.print("[bold cyan]GitHub Changes Summary[/]")
    console.print("=" * 80)

    # Counts by type
    by_type = Counter(ch.type.value for ch in changes)
    type_table = Table(show_header=True, title="By Type")
    type_table.add_column("Type", style="magenta", no_wrap=True)
    type_table.add_column("Count", style="yellow", no_wrap=True)
    for t, c in sorted(by_type.items()):
        type_table.add_row(t, str(c))
    console.print(type_table)

    # Counts by repo
    by_repo = Counter(ch.repo_full_name for ch in changes)
    repo_table = Table(show_header=True, title="By Repository")
    repo_table.add_column("Repository", style="green", no_wrap=True)
    repo_table.add_column("Count", style="yellow", no_wrap=True)
    for r, c in sorted(by_repo.items()):
        repo_table.add_row(r, str(c))
    console.print(repo_table)
