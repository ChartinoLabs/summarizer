"""CLI definition for the application."""

from datetime import datetime
from enum import Enum
from typing import Annotated

import typer
from dotenv import load_dotenv

from .config import AppConfig

# Load environment variables from .env before initializing the Typer app
load_dotenv()

app = typer.Typer(pretty_exceptions_enable=False)


class TimeDisplayFormat(str, Enum):
    """Time display format."""

    h12 = "12h"
    h24 = "24h"


@app.command()
def main(
    user_email: Annotated[
        str, typer.Option(..., envvar="USER_EMAIL", prompt="Enter your Cisco email")
    ],
    webex_token: Annotated[
        str,
        typer.Option(
            ...,
            envvar="WEBEX_TOKEN",
            prompt="Enter your Webex access token",
            hide_input=True,
        ),
    ],
    target_date: Annotated[
        str, typer.Option(..., help="Date in YYYY-MM-DD format", metavar="YYYY-MM-DD")
    ],
    context_window_minutes: Annotated[
        int, typer.Option(help="Context window in minutes")
    ] = 15,
    passive_participation: Annotated[
        bool,
        typer.Option(help="Include conversations where you only received messages?"),
    ] = False,
    time_display_format: Annotated[
        TimeDisplayFormat, typer.Option(help="Time display format ('12h' or '24h')")
    ] = TimeDisplayFormat.h12,
    room_chunk_size: Annotated[int, typer.Option(help="Room fetch chunk size")] = 50,
) -> None:
    """Webex Summarizer CLI (Typer config parsing demo)."""
    # Parse target_date
    try:
        parsed_date = datetime.strptime(target_date, "%Y-%m-%d")
    except ValueError as exc:
        typer.echo("[red]Invalid date format. Please use YYYY-MM-DD.[/red]")
        raise typer.Exit(1) from exc

    typer.echo("Parsed config:")
    typer.echo(f"  user_email: {user_email}")
    typer.echo(f"  webex_token: {'*' * len(webex_token) if webex_token else ''}")
    typer.echo(f"  target_date: {parsed_date}")
    typer.echo(f"  context_window_minutes: {context_window_minutes}")
    typer.echo(f"  passive_participation: {passive_participation}")
    typer.echo(f"  time_display_format: {time_display_format.value}")
    typer.echo(f"  room_chunk_size: {room_chunk_size}")

    # Construct AppConfig
    config = AppConfig(
        webex_token=webex_token,
        user_email=user_email,
        target_date=parsed_date,
        context_window_minutes=context_window_minutes,
        passive_participation=passive_participation,
        time_display_format=time_display_format.value,
        room_chunk_size=room_chunk_size,
    )
    typer.echo("\nConstructed AppConfig:")
    typer.echo(repr(config))


if __name__ == "__main__":
    app()
