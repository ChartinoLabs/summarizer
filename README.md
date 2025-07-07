# Summarizer

Summarizes the work a person has done within a given day across multiple applications. This is useful for asynchronous scrum check-ins or for use in other general work reporting systems.

## Supported Applications

### Webex

Leverages the Webex API to identify what conversations the authenticated user has taken part in throughout the day. Information includes:

- Who the conversation was with (whether it was a direct message or a group conversation)
- When the conversation started and ended
- The duration of the conversation

## Installation

This script requires Python 3.10 or later and uses [uv](https://github.com/astral-sh/uv) for dependency management. Once uv is installed correctly, execute the following command:

```bash
uv sync
```

Or, to install in editable mode with development dependencies:

```bash
uv sync --all-extras
```

## Usage

Run the application through the following command:

```bash
uv run summarizer --help
```

### Single Date

You can provide your email address and Webex token via CLI options, environment variables, or interactive prompt (prompting for email first, then token):

```bash
uv run summarizer --user-email=you@example.com --webex-token=YOUR_TOKEN --target-date=2024-06-01
```

Or with environment variables:

```bash
export USER_EMAIL=you@example.com
export WEBEX_TOKEN=YOUR_TOKEN
uv run summarizer --target-date=2024-06-01
```

If not provided, you will be prompted for your email and token interactively.

### Date Range

You can also specify a date range to summarize activity over multiple days. The `--start-date` and `--end-date` options are mutually exclusive with `--target-date`.

```bash
uv run summarizer --user-email=you@example.com --webex-token=YOUR_TOKEN --start-date=2024-06-01 --end-date=2024-06-03
```

### Other Options

Other options (with defaults):

- `--target-date`: The specific date to summarize (e.g., `2024-06-01`).
- `--start-date`: The start date for a range summary.
- `--end-date`: The end date for a range summary.
- `--context-window-minutes`: Context window in minutes (default: 15)
- `--passive-participation`: Include conversations where you only received messages (default: False)
- `--time-display-format`: Time display format ('12h' or '24h', default: '12h')
- `--room-chunk-size`: Room fetch chunk size (default: 50)
- `--debug`: Enable debug logging.
