# Webex Summarizer

A simple Python script that uses the Webex API to return a list of messages the user has sent in Webex spaces, as well as the Webex space the message was sent in and the time.

## Installation

This script generally requires Python 3.9 or later and uses [uv](https://github.com/astral-sh/uv) for dependency management. Once uv is installed correctly, execute the following command:

```bash
uv pip install -r requirements.txt
```

Or, to install in editable mode with development dependencies:

```bash
uv pip install -e "." --with dev
```

## Usage

Run the application through the following command:

```bash
uv run python -m webex_summarizer.cli --help
```

Or, if you have already installed dependencies into your environment, you can simply run:

```bash
python -m webex_summarizer.cli --help
```

You can provide your email address and Webex token via CLI options, environment variables, or interactive prompt (prompting for email first, then token):

```bash
uv run python -m webex_summarizer.cli --user-email=you@example.com --webex-token=YOUR_TOKEN --target-date=2024-06-01
```

Or with environment variables:

```bash
export USER_EMAIL=you@example.com
export WEBEX_TOKEN=YOUR_TOKEN
uv run python -m webex_summarizer.cli --target-date=2024-06-01
```

If not provided, you will be prompted for your email and token interactively.

Other options (with defaults):
- `--context-window-minutes`: Context window in minutes (default: 15)
- `--passive-participation`: Include conversations where you only received messages (default: False)
- `--time-display-format`: Time display format ('12h' or '24h', default: '12h')
- `--room-chunk-size`: Room fetch chunk size (default: 50)
