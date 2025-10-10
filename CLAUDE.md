# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Python CLI application that summarizes work activity across multiple platforms (Webex and GitHub) for daily reporting. It uses `uv` for dependency management and `typer` for CLI interface.

## Development Commands

### Environment Setup
```bash
# Install dependencies
uv sync

# Install with development dependencies
uv sync --all-extras
```

### Running the Application

#### Webex Authentication (Choose One)

**Option 1: OAuth 2.0 (Recommended)**
```bash
# Set up OAuth credentials
export USER_EMAIL=you@example.com
export WEBEX_OAUTH_CLIENT_ID=your_client_id
export WEBEX_OAUTH_CLIENT_SECRET=your_client_secret

# Authenticate once (opens browser)
uv run summarizer webex login

# Check authentication status
uv run summarizer webex status

# Run summarizer (uses stored OAuth tokens)
uv run summarizer --target-date=2024-06-01
```

**Option 2: Manual Token (Legacy)**
```bash
# Using manual token (expires in 12 hours)
export USER_EMAIL=you@example.com
export WEBEX_TOKEN=your_manual_token
uv run summarizer --target-date=2024-06-01
```

#### GitHub Authentication
```bash
export GITHUB_TOKEN=your_github_token
```

#### Basic Usage
```bash
# Show help
uv run summarizer --help

# Run with both platforms
uv run summarizer --target-date=2024-06-01

# Run with specific platforms disabled
uv run summarizer --no-github --target-date=2024-06-01
uv run summarizer --no-webex --target-date=2024-06-01
```

#### OAuth Management Commands
```bash
# Authenticate with Webex OAuth
uv run summarizer webex login

# Check authentication status and refresh tokens
uv run summarizer webex status

# Logout (remove stored credentials)
uv run summarizer webex logout
```

### Testing
```bash
# Run tests
uv run pytest

# Run tests with coverage
uv run pytest --cov=summarizer
```

### Code Quality
```bash
# Run linting and formatting
uv run ruff check .
uv run ruff format .

# Run complexity analysis
uv run xenon --max-absolute=B --max-modules=B --max-average=B summarizer/

# Run security checks
uv run bandit -r summarizer/

# Install and run pre-commit hooks
uv run pre-commit install
uv run pre-commit run --all-files
```

## Architecture

### Core Structure
- **CLI Layer** (`summarizer/cli.py`): Typer-based CLI with unified Webex + GitHub support
- **Platform Modules**: Each platform (webex/, github/) has config, client, and runner components
- **Common Module** (`summarizer/common/`): Shared models, configuration base classes, logging, and UI utilities

### Key Components

#### Configuration System
- `BaseConfig`: Abstract base for platform-agnostic configuration
- `WebexConfig`: Webex-specific settings (OAuth/manual tokens, email, context windows)
- `GithubConfig`: GitHub-specific settings (tokens, API URLs, org/repo filters)

#### Authentication System
- **Webex OAuth 2.0**: PKCE-secured authorization flow with automatic token refresh
  - Access tokens: 14-day expiration
  - Refresh tokens: 90-day expiration
  - Secure credential storage in `~/.config/summarizer/`
- **Webex Manual Token**: Legacy 12-hour token support (fallback)
- **GitHub**: Personal access token authentication

#### Data Models
- **Webex**: `User`, `Message`, `Conversation`, `Thread` models for chat data
- **GitHub**: `Change` model with `ChangeType` enum (commits, issues, PRs, comments, reviews)
- **Common**: `SpaceType` enum for conversation types

#### Platform Architecture
Each platform follows the same pattern:
1. **Config**: Platform-specific configuration container
2. **Client**: API interaction layer (REST/GraphQL)
3. **Runner**: Orchestration and business logic layer

### Date Handling
- Supports both single dates (`--target-date`) and date ranges (`--start-date`/`--end-date`)
- Uses datetime objects internally with YYYY-MM-DD CLI format
- Mutually exclusive validation between single date and range modes

### Multi-Platform Support
- Platform activation based on credential presence and explicit disable flags
- Unified CLI with platform-specific sections
- CSV parsing for organization and repository filters
- Change type filtering with include/exclude options

## Development Notes

### Dependencies
- **Core**: `typer`, `pydantic-settings`, `requests`, `rich`
- **Webex**: `webexpythonsdk`
- **Dev**: `ruff`, `pytest`, `bandit`, `xenon`, `pre-commit`

### Code Standards
- Uses Ruff for linting with comprehensive rule set (pycodestyle, flake8-bugbear, pep8-naming, etc.)
- Google-style docstrings enforced via pydocstyle
- Complexity limits enforced via xenon (max B-grade)
- Security scanning via bandit
- Type hints required (flake8-annotations)

### Testing Structure
- Tests located in `tests/` directory
- Async test support configured via pytest-asyncio
- Mock HTTP responses using `responses` library
- Platform-specific test modules mirror source structure
