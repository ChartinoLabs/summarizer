"""Console UI components for webex-summarizer."""

from collections import Counter
from datetime import datetime, timedelta

import humanize
from rich.console import Console
from rich.markup import escape
from rich.panel import Panel
from rich.table import Table

from summarizer.common.models import Change, Conversation, Meeting, MeetingSummary

console = Console()


def _e(value: object) -> str:
    """Escape user-generated content before Rich renders it.

    Webex messages, display names, and meeting titles routinely contain
    bracketed substrings like ``[/opt/foo/bar]`` (file paths, log tags,
    literal Python tracebacks). Rich treats ``[...]`` as markup, so these
    raise ``rich.errors.MarkupError`` when handed directly to a Panel or
    Table cell. Always pass user content through this helper first.
    """
    return escape(str(value) if value is not None else "")


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
                _e(msg.get("space", "-")),
                _e(msg.get("text", "-")),
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
        participants = ", ".join([_e(u.display_name) for u in convo.participants])
        duration = (
            humanize.precisedelta(
                timedelta(seconds=convo.duration_seconds), minimum_unit="seconds"
            )
            if convo.duration_seconds is not None
            else "-"
        )
        header = (
            f"[bold]Conversation {_e(convo.id)}[/] | "
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
                _e(msg.sender.display_name),
                _e(msg.content),
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
        participants = ", ".join([_e(u.display_name) for u in convo.participants])

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
            _e(convo.id),
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


# ================================
# Webex Meetings UI components
# ================================


def _render_meeting_summary(summary: MeetingSummary) -> None:
    """Render an AI summary sub-panel for a meeting."""
    summary_parts: list[str] = []
    if summary.overview:
        summary_parts.append(f"[bold]Overview:[/] {_e(summary.overview)}")
    if summary.notes:
        notes = "\n".join(f"  - {_e(n)}" for n in summary.notes)
        summary_parts.append(f"[bold]Notes:[/]\n{notes}")
    if summary.action_items:
        items = "\n".join(f"  - {_e(a)}" for a in summary.action_items)
        summary_parts.append(f"[bold]Action Items:[/]\n{items}")

    if summary_parts:
        console.print(
            Panel(
                "\n\n".join(summary_parts),
                title="AI Summary",
                style="blue",
            )
        )


def _render_transcript_snippets(snippets: list, max_lines: int) -> None:
    """Render a transcript snippet table for a meeting."""
    table = Table(show_header=True, title="Transcript")
    table.add_column("Speaker", style="green", no_wrap=True)
    table.add_column("Text", style="white", no_wrap=False, overflow="fold")

    for snippet in snippets[:max_lines]:
        table.add_row(_e(snippet.speaker.display_name), _e(snippet.text))

    console.print(table)

    remaining = len(snippets) - max_lines
    if remaining > 0:
        console.print(f"  [dim]... and {remaining} more transcript lines[/]")


def display_meetings(
    meetings: list[Meeting],
    time_display_format: str = "12h",
    max_transcript_lines: int = 10,
) -> None:
    """Display detailed information for each meeting.

    For each meeting, shows a Panel header with metadata, an optional
    AI summary sub-panel, and an optional transcript table.

    Args:
        meetings: List of Meeting dataclasses to display
        time_display_format: "12h" or "24h"
        max_transcript_lines: Max transcript snippets shown per meeting
    """
    if not meetings:
        console.print("[yellow]No meetings found for this date.[/]")
        return

    console.print("\n" + "=" * 80)
    console.print("[bold cyan]Webex Meetings[/]")
    console.print("=" * 80)

    sorted_meetings = sorted(meetings, key=lambda m: m.start_time)

    for meeting in sorted_meetings:
        start_fmt = _format_datetime(meeting.start_time, time_display_format)
        end_fmt = _format_datetime(meeting.end_time, time_display_format)
        duration = humanize.precisedelta(
            timedelta(seconds=meeting.duration_seconds), minimum_unit="seconds"
        )
        participants_str = (
            ", ".join(_e(p.display_name) for p in meeting.participants)
            if meeting.participants
            else "-"
        )

        header = (
            f"[bold]{_e(meeting.title)}[/]\n"
            f"[green]Host:[/] {_e(meeting.host.display_name)} | "
            f"[cyan]Start:[/] {start_fmt} | [cyan]End:[/] {end_fmt} | "
            f"[yellow]Duration:[/] {duration}"
        )
        if meeting.participants:
            header += f"\n[magenta]Participants:[/] {participants_str}"

        console.print(Panel(header, style="bold white"))

        if meeting.summary:
            _render_meeting_summary(meeting.summary)

        if meeting.transcript_snippets:
            snippet_label = f"{len(meeting.transcript_snippets)} snippets"
            if meeting.transcript_vtt:
                snippet_label += " [dim](full VTT available)[/]"
            console.print(f"[dim]{snippet_label}[/]")
            _render_transcript_snippets(
                meeting.transcript_snippets, max_transcript_lines
            )

        console.print()  # blank line between meetings


def display_meetings_summary(
    meetings: list[Meeting],
    time_display_format: str = "12h",
) -> None:
    """Display a summary table of all meetings with aggregate statistics.

    Args:
        meetings: List of Meeting dataclasses
        time_display_format: "12h" or "24h"
    """
    if not meetings:
        return

    console.print("\n" + "=" * 80)
    console.print("[bold cyan]Meetings Summary[/]")
    console.print("=" * 80)

    sorted_meetings = sorted(meetings, key=lambda m: m.start_time)

    table = Table(show_header=True, title="Meeting Overview")
    table.add_column("Title", style="bold blue", no_wrap=False, overflow="fold")
    table.add_column("Start", style="cyan", no_wrap=True)
    table.add_column("End", style="cyan", no_wrap=True)
    table.add_column("Duration", style="yellow", no_wrap=True)
    table.add_column("Summary?", style="green", no_wrap=True)
    table.add_column("Transcript?", style="green", no_wrap=True)

    for meeting in sorted_meetings:
        start_str = _format_datetime(meeting.start_time, time_display_format)
        end_str = _format_datetime(meeting.end_time, time_display_format)
        duration = humanize.precisedelta(
            timedelta(seconds=meeting.duration_seconds), minimum_unit="seconds"
        )
        has_summary = "Yes" if meeting.summary else "No"
        has_transcript = "Yes" if meeting.transcript_snippets else "No"
        if meeting.transcript_vtt:
            has_transcript += " [dim](full VTT)[/]"
        table.add_row(
            _e(meeting.title),
            start_str,
            end_str,
            duration,
            has_summary,
            has_transcript,
        )

    console.print(table)

    # Aggregate statistics
    total_meetings = len(meetings)
    total_duration = sum(m.duration_seconds for m in meetings)
    if total_duration > 0:
        duration_summary = humanize.precisedelta(
            timedelta(seconds=total_duration), minimum_unit="seconds"
        )
    else:
        duration_summary = "0 seconds"

    console.print("\n[bold]Meeting Statistics:[/]")
    console.print(f"Total meetings: [bold green]{total_meetings}[/]")
    console.print(f"Total meeting time: [bold yellow]{duration_summary}[/]")


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


def print_cache_indicator(platform: str, fetched_at: datetime | None) -> None:
    """Print a cache hit indicator with fetch timestamp."""
    ts = fetched_at.strftime("%Y-%m-%d %H:%M:%S") if fetched_at else "unknown"
    console.print(f"  [dim italic]{platform} data loaded from cache (fetched {ts})[/]")


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
        table.add_row(time_str, ch.type.value, _e(ch.repo_full_name), _e(ch.title))

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
