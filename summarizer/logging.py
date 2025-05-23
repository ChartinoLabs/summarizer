"""Logging setup utility for the summarizer application."""

import logging
from datetime import datetime
from pathlib import Path


def setup_logging() -> None:
    """Configure logging to file with timestamped filename."""
    # Create the logs directory if it doesn't exist
    Path("logs").mkdir(exist_ok=True)
    log_filename = f"logs/summarizer-{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}.log"
    logging.basicConfig(
        filename=log_filename,
        filemode="a",
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        level=logging.INFO,  # Default level; can be changed to DEBUG if needed
    )
