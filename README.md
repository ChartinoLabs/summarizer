# Summarizer

Summarizes the work a person has done within a given day across multiple applications, or retrieves the complete message history from specific Webex rooms/conversations. This is useful for asynchronous scrum check-ins, work reporting systems, or analyzing conversation history with specific teams or individuals.

## Supported Applications

### Webex

Leverages the Webex API to provide two main capabilities:

**Date-Based Activity Summary:**

- Identifies what conversations the authenticated user participated in on specific dates
- Shows who the conversation was with (direct message or group conversation)
- Displays when conversations started and ended, plus duration
- Groups messages into logical conversation windows

**Room-Specific Message History:**

- Retrieves complete message history from specific Webex rooms or DMs
- Find rooms by exact Room ID, room name, or person name for DMs
- Optional date filtering to narrow down results
- Configurable message limits (default: 1000 messages)

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

### Authentication

All commands require your Cisco email and Webex token. You can provide these via:

1. **CLI options**: `--user-email` and `--webex-token`
2. **Environment variables**: `USER_EMAIL` and `WEBEX_TOKEN`
3. **Interactive prompt**: You'll be prompted if not provided

**Get your Webex token**: Visit [https://developer.webex.com/docs/getting-started](https://developer.webex.com/docs/getting-started)

### Date-Based Activity Summary

Summarizes your Webex activity for specific dates.

#### Single Date

```bash
# With CLI options
uv run summarizer --user-email=you@example.com --webex-token=YOUR_TOKEN --target-date=2024-06-01

# With environment variables
export USER_EMAIL=you@example.com
export WEBEX_TOKEN=YOUR_TOKEN
uv run summarizer --target-date=2024-06-01

# Interactive prompts (if no email/token provided)
uv run summarizer --target-date=2024-06-01
```

#### Date Range

Summarize activity over multiple days (`--start-date` and `--end-date` are mutually exclusive with `--target-date`):

```bash
uv run summarizer --user-email=you@example.com --webex-token=YOUR_TOKEN --start-date=2024-06-01 --end-date=2024-06-03

# With environment variables
export USER_EMAIL=you@example.com
export WEBEX_TOKEN=YOUR_TOKEN
uv run summarizer --start-date=2024-06-01 --end-date=2024-06-03
```

### Room-Specific Message History

Retrieve complete message history from specific Webex rooms or DMs.

#### Find Room by ID

Use exact Webex Room ID (most precise method):

```bash
uv run summarizer --user-email=you@example.com --webex-token=YOUR_TOKEN --room-id=Y2lzY29zcGFyazovL3VzL1JPT00vYmJjZWEwN2QtOTU4...

# With custom message limit
uv run summarizer --user-email=you@example.com --webex-token=YOUR_TOKEN --room-id=Y2lzY29zcGFyazovL3VzL1JPT00vYmJjZWEwN2QtOTU4... --max-messages=500
```

#### Find Room by Name

Use exact room name (case-sensitive):

```bash
uv run summarizer --user-email=you@example.com --webex-token=YOUR_TOKEN --room-name="AskCX Test Automation"

# With environment variables
export USER_EMAIL=you@example.com
export WEBEX_TOKEN=YOUR_TOKEN
uv run summarizer --room-name="Daily Standup"
```

#### Find DM by Person Name

Use exact person display name to find direct message conversation:

```bash
uv run summarizer --user-email=you@example.com --webex-token=YOUR_TOKEN --person-name="Andrea Testino"

# With environment variables
export USER_EMAIL=you@example.com
export WEBEX_TOKEN=YOUR_TOKEN
uv run summarizer --person-name="John Smith"
```

#### Combine Room Search with Date Filtering

Retrieve messages from a specific room, filtered by date:

```bash
# Get messages from Andrea's DM for a specific date
uv run summarizer --user-email=you@example.com --webex-token=YOUR_TOKEN --person-name="Andrea Testino" --target-date=2024-06-01

# Get messages from team room for date range
uv run summarizer --user-email=you@example.com --webex-token=YOUR_TOKEN --room-name="Team Meeting" --start-date=2024-06-01 --end-date=2024-06-03

# With environment variables and custom message limit
export USER_EMAIL=you@example.com
export WEBEX_TOKEN=YOUR_TOKEN
uv run summarizer --person-name="Andrea Testino" --target-date=2024-06-01 --max-messages=2000
```

### Complete Command Reference

#### Authentication Options

- `--user-email`: Your Cisco email address (or set `USER_EMAIL` env var)
- `--webex-token`: Your Webex access token (or set `WEBEX_TOKEN` env var)

#### Date-Based Search Options

- `--target-date`: Specific date to summarize (format: `YYYY-MM-DD`)
- `--start-date`: Start date for range summary (format: `YYYY-MM-DD`)
- `--end-date`: End date for range summary (format: `YYYY-MM-DD`)

**Note:** `--target-date` is mutually exclusive with `--start-date`/`--end-date`

#### Room-Based Search Options

- `--room-id`: Exact Webex room ID to retrieve messages from
- `--room-name`: Exact room name to search for (case-sensitive)
- `--person-name`: Exact person display name to find DM with

**Note:** Only one room identification option can be used at a time

#### Message and Display Options

- `--max-messages`: Maximum number of messages to retrieve from room (default: 1000)
- `--context-window-minutes`: Context window for grouping messages in minutes (default: 15)
- `--passive-participation`: Include conversations where you only received messages (default: False)
- `--time-display-format`: Time display format - '12h' or '24h' (default: '12h')
- `--room-chunk-size`: Room fetch chunk size for date-based searches (default: 50)

#### Utility Options

- `--debug`: Enable debug logging
- `--help`: Show help message and exit

### Usage Examples by Scenario

#### Daily Standup Reporting

```bash
# Yesterday's activity summary
uv run summarizer --target-date=2024-06-01

# Last week's activity
uv run summarizer --start-date=2024-05-27 --end-date=2024-06-01
```

#### Project Investigation

```bash
# All messages from project room
uv run summarizer --room-name="Project Alpha Development"

# Project room activity for specific sprint
uv run summarizer --room-name="Project Alpha Development" --start-date=2024-06-01 --end-date=2024-06-14
```

#### 1:1 Conversation Review

```bash
# All recent DMs with manager
uv run summarizer --person-name="Sarah Johnson" --max-messages=500

# DMs with teammate for specific date
uv run summarizer --person-name="Andrea Testino" --target-date=2024-06-01
```

#### Troubleshooting

```bash
# Debug mode for API issues
uv run summarizer --debug --target-date=2024-06-01

# Find specific room ID for future use
uv run summarizer --debug --room-name="Hard to Remember Room Name"
```
