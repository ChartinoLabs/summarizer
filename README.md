# Summarizer

Summarizes the work a person has done within a given day across multiple applications. This is useful for asynchronous scrum check-ins or for use in other general work reporting systems.

## Supported Applications

### Webex

Leverages the Webex API to identify what conversations the authenticated user has taken part in throughout the day. Information includes:

- Who the conversation was with (whether it was a direct message or a group conversation)
- When the conversation started and ended
- The duration of the conversation

### GitHub

Tracks GitHub activity including commits, pull requests, issues, reviews, and comments. Supports both GitHub.com and GitHub Enterprise. Information includes:

- Commits pushed to repositories
- Pull requests created and reviewed
- Issues created and commented on
- Code review activity
- Repository and organization filtering

## Installation

This script requires Python 3.10 or later and uses [uv](https://github.com/astral-sh/uv) for dependency management. Once uv is installed correctly, execute the following command:

```bash
uv sync
```

Or, to install in editable mode with development dependencies:

```bash
uv sync --all-extras
```

## Authentication Setup

### Webex OAuth 2.0 (Recommended)

The recommended authentication method uses OAuth 2.0, which provides secure, long-lived tokens that automatically refresh.

#### 1. Create a Webex Integration

1. Visit the [Webex for Developers](https://developer.webex.com/) site
2. Sign in with your Webex account
3. Go to **My Apps** → **Create a New App** → **Create an Integration**
4. Fill in the integration details:
   - **Integration Name**: e.g., "Work Summarizer"
   - **Description**: Brief description of your usage
   - **Redirect URI**: `http://localhost:8080/callback` (the app will use available ports 8080-8089)
   - **Scopes**: Select the following required scopes:
     - `spark:messages_read` - Read your messages
     - `spark:rooms_read` - Read your rooms/spaces
     - `spark:people_read` - Read user profile information
5. Click **Add Integration**
6. Save your **Client ID** and **Client Secret** (keep these secure!)

#### 2. Configure OAuth Credentials

Set up your OAuth credentials using environment variables:

```bash
export USER_EMAIL=you@example.com
export WEBEX_OAUTH_CLIENT_ID=your_client_id_here
export WEBEX_OAUTH_CLIENT_SECRET=your_client_secret_here
```

#### 3. Authenticate with Webex

Run the OAuth authentication flow (one-time setup):

```bash
uv run summarizer webex login
```

This will:
- Start a temporary local web server to handle the OAuth callback
- Open your browser to Webex's authorization page
- Automatically capture the authorization code after you approve
- Exchange the code for access and refresh tokens
- Save your credentials securely and shut down the temporary server

#### 4. Verify Authentication

Check your authentication status:

```bash
uv run summarizer webex status
```

Your tokens will automatically refresh when needed (access tokens last 14 days, refresh tokens last 90 days).

### Legacy Manual Token (Not Recommended)

You can still use manual tokens, but they expire every 12 hours and require manual renewal:

```bash
export USER_EMAIL=you@example.com
export WEBEX_TOKEN=your_manual_token
```

To get a manual token:
1. Visit https://developer.webex.com/docs/getting-started
2. Sign in and copy your personal access token
3. Note: This method is deprecated and will require frequent re-authentication

## Usage

Run the application through the following command:

```bash
uv run summarizer --help
```

### Basic Usage

Once authenticated, run the summarizer for any date:

```bash
uv run summarizer --target-date=2024-06-01
```

Or specify credentials via CLI options:

```bash
uv run summarizer --user-email=you@example.com --webex-oauth-client-id=CLIENT_ID --webex-oauth-client-secret=CLIENT_SECRET --target-date=2024-06-01
```

### Date Range

You can also specify a date range to summarize activity over multiple days. The `--start-date` and `--end-date` options are mutually exclusive with `--target-date`.

```bash
uv run summarizer --start-date=2024-06-01 --end-date=2024-06-03
```

### OAuth Management Commands

The following commands help manage your Webex OAuth authentication:

```bash
# Authenticate with Webex (opens browser)
uv run summarizer webex login

# Check authentication status and refresh tokens if needed
uv run summarizer webex status

# Remove stored credentials (logout)
uv run summarizer webex logout
```

### GitHub Authentication

For GitHub integration, set your personal access token:

```bash
export GITHUB_TOKEN=your_github_token
```

You can create a GitHub token at: https://github.com/settings/tokens

### Multi-Platform Usage

You can run with both Webex and GitHub, or disable specific platforms:

```bash
# Both platforms (default)
uv run summarizer --target-date=2024-06-01

# Only Webex
uv run summarizer --no-github --target-date=2024-06-01

# Only GitHub  
uv run summarizer --no-webex --target-date=2024-06-01
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

## Troubleshooting

### Webex OAuth Issues

**"No platforms are active" error:**
- Ensure you have set `USER_EMAIL` and either `WEBEX_TOKEN` or both `WEBEX_OAUTH_CLIENT_ID` and `WEBEX_OAUTH_CLIENT_SECRET`
- Run `uv run summarizer webex status` to check your authentication status
- If using OAuth, run `uv run summarizer webex login` to re-authenticate

**Browser doesn't open during login:**
- The authorization URL will be displayed in the terminal
- Manually copy and paste the URL into your browser
- Complete the authorization - the callback will be handled automatically
- If you see a "connection refused" error, the callback server may have failed to start

**"Invalid redirect URI" error:**
- Ensure your Webex integration is configured with redirect URI: `http://localhost:8080/callback`
- The redirect URI in your integration settings must match exactly
- The app automatically tries ports 8080-8089 if 8080 is busy

**"Cannot start callback server" error:**
- Ensure ports 8080-8089 are not blocked by firewall
- Check that no other applications are using all these ports
- Try running from a different network location if corporate firewall blocks local servers

**Token refresh failures:**
- If refresh tokens expire (after 90 days), re-authenticate with `uv run summarizer webex login`
- Check network connectivity and firewall settings

### GitHub Issues

**"Unauthorized" error:**
- Verify your `GITHUB_TOKEN` is valid and has the required scopes
- For GitHub Enterprise, set `GITHUB_API_URL` environment variable

### General Issues

**Empty results:**
- Check that the target date has actual activity
- Verify your timezone settings
- Use `--debug` flag for detailed logging
- Ensure you have access to the rooms/repositories in question

### Getting Help

For additional support:
1. Run with `--debug` flag to see detailed logs
2. Check the [Issues](https://github.com/ChartinoLabs/summarizer/issues) page
3. Verify your authentication status with `uv run summarizer webex status`

### Security Notes

- OAuth credentials are stored securely in `~/.config/summarizer/`
- Never share your Client Secret or access tokens
- Use environment variables or secure credential storage
- Regularly review and rotate your API tokens
