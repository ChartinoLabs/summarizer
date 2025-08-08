## Goal

Add first-class support for summarizing a user’s GitHub activity for a target date or date range, across GitHub.com or a GitHub Enterprise instance. “Activity/Changes” include:

- Commits
- Issues created
- Pull requests created
- Issue comments
- Pull request comments
- Pull request reviews


## High-level design

- **Module structure**: mirror the `webex` integration with a new `summarizer/github/` package:
  - `summarizer/github/config.py`: configuration, environment parsing
  - `summarizer/github/client.py`: GitHub API client (GraphQL preferred, REST fallback)
  - `summarizer/github/runner.py`: orchestrates fetching and rendering results
  - `summarizer/github/__init__.py`
- **CLI**: extend `summarizer/cli.py` to auto-detect active platforms based on provided credentials (single unified command; no subcommands). Reuse existing date/range parsing helpers.
- **Config-driven host**: support GitHub Enterprise via configurable API endpoints; never hardcode `github.com`.
- **Data model**: introduce a platform-agnostic `Change` model in `summarizer/common/models.py` to represent GitHub “changes”. The GitHub runner will render these with new console helpers (separate from the Webex conversation grouping).
- **Runner strategy**: `GithubRunner` will override `run()` to fetch and display `Change` items instead of using the Webex conversation grouping pipeline.
- **APIs**: prefer GraphQL v4 (User.contributionsCollection) for commits/issues/PRs/reviews within a time window; use REST v3 for comments if needed (issue comments / PR comments) where GraphQL coverage is insufficient.
- **Pagination & rate limits**: handle pagination; respect rate limit headers; allow a low-rate “safe mode”.


## CLI design (single command, auto-detect platforms)

Keep a single `summarizer` command that summarizes all supported platforms where valid credentials are present. Do not require explicit `--webex` or `--github` flags.

- Invoke as: `uv run summarizer [flags...]`
- Detection rules:
  - If valid Webex credentials are present, include Webex activity.
  - If valid GitHub credentials are present, include GitHub changes.
  - If no valid credentials for any platform are found, exit with a helpful error.
  - If credentials are provided for a platform but invalid, exit with an error (fail the run).

Shared date options (reuse existing helpers):

- `--target-date YYYY-MM-DD`
- `--start-date YYYY-MM-DD --end-date YYYY-MM-DD`

Webex options (all optional; if omitted, Webex is skipped):

- `--user-email` (env: `USER_EMAIL`)
- `--webex-token` (env: `WEBEX_TOKEN`)
- `--room-chunk-size` (existing) remains

GitHub options (all optional; if omitted, GitHub is skipped):

- `--github-token` (env: `GITHUB_TOKEN`)
- `--github-api-url` (env: `GITHUB_API_URL`) default `https://api.github.com`
- `--github-graphql-url` (env: `GITHUB_GRAPHQL_URL`) default `${GITHUB_API_URL}/graphql`
- `--github-user` (env: `GITHUB_USER`) default derive from token (`viewer` query)
- `--org` (repeatable) (env: `GITHUB_ORGS`, comma-separated): restrict search to specific orgs
- `--repo` (repeatable) (env: `GITHUB_REPOS`, comma-separated `owner/name`): restrict to specific repos
- `--include` (repeatable, choices: commits,issues,prs,issue_comments,pr_comments,reviews) default all
- `--exclude` (repeatable) for the same choices
- `--safe-rate` boolean: back off when remaining rate is low


## Configuration

Create `GithubConfig(BaseConfig)` similar to `WebexConfig` with fields:

- `github_token: str`
- `api_url: str` (e.g., `https://github.myco.com/api/v3`)
- `graphql_url: str` (e.g., `https://github.myco.com/api/graphql`)
- `user: str | None` (login; if None, resolve via `viewer`)
- `org_filters: list[str]`
- `repo_filters: list[str]` (each `owner/name`)
- `include_types: set[ChangeType]`
- `safe_rate: bool`
- Inherit from `BaseConfig` to reuse `target_date`, `context_window_minutes`, `passive_participation`, `time_display_format` (even if not used by GitHub runner)


## Data model

Add to `summarizer/common/models.py`:

- `enum ChangeType { COMMIT, ISSUE, PULL_REQUEST, ISSUE_COMMENT, PR_COMMENT, REVIEW }`
- `@dataclass Change` with fields:
  - `id: str`
  - `type: ChangeType`
  - `timestamp: datetime`
  - `repo_full_name: str` (e.g., `owner/name`)
  - `title: str`
  - `url: str`
  - `summary: str | None` (short body/description)
  - `metadata: dict[str, str]` (e.g., branch, sha, state)

Add console helpers in `summarizer/common/console_ui.py`:

- `display_changes(changes: list[Change])` showing grouped-by-type tables
- `display_changes_summary(changes: list[Change])` totals by type and by repo

These functions do not affect existing Webex display.


## GitHub client approach

- Use GraphQL for aggregated contributions where possible:
  - `viewer { login }` when `--github-user` not provided
  - `user(login: ...) { contributionsCollection(from:, to:) { ... } }`
  - Fetch:
    - commitContributionsByRepository (commit counts and commits with timestamps)
    - issueContributions (issues created)
    - pullRequestContributions (PRs created)
    - pullRequestReviewContributions (reviews)
  - Filter repositories by `org_filters` or `repo_filters` if provided
- Use REST for comments:
  - Issue comments: `GET /repos/{owner}/{repo}/issues/comments` with `since`/filtering
  - PR review comments: `GET /repos/{owner}/{repo}/pulls/comments` with `since`
  - If GraphQL adequately covers comments in your GHE version, prefer GraphQL; keep REST fallback for portability
- Respect pagination (`per_page`, `Link` headers) and collect across all pages
- Respect rate limit headers and pause/backoff if `--safe-rate` is enabled
- Accept custom endpoints (Enterprise):
  - REST base: `GITHUB_API_URL` (e.g., `https://ghe.example.com/api/v3`)
  - GraphQL: `GITHUB_GRAPHQL_URL` (e.g., `https://ghe.example.com/api/graphql`)


## Orchestration & runner behavior

- Introduce a lightweight orchestrator in `summarizer/cli.py` that determines active platforms based on credentials and runs them for each date.
  - For each date (single or range):
    - Print a date header once
    - If Webex is active: construct `WebexConfig`, run `WebexRunner(config).run(date_header=False)`
    - If GitHub is active: construct `GithubConfig`, run `GithubRunner(config).run(date_header=False)`
  - If any active platform fails authentication in `connect()`, exit with non-zero status and error message (do not continue to others).

- `GithubRunner(BaseRunner)`:
  - `connect()`: validate token by calling `viewer` and resolve `user` login
  - `run(date_header: bool)`: 
    - determine `[from, to)` bounds for single date (local midnight to midnight next day) or per-day iteration via CLI
    - fetch contributions and comments
    - map to `Change` objects
    - render via `display_changes` then `display_changes_summary`


## Mapping rules (GitHub → Change)

- Commits: one `Change` per commit with `metadata.sha`, `metadata.branch` (if available), `summary` first line of message
- Issues: `title` issue title; `summary` truncated body; `metadata.number`, `metadata.state`
- PRs: `title` PR title; `summary` truncated body; `metadata.number`, `metadata.state`, `metadata.base`/`head`
- Issue comments: `title` `commented on #<number> <title>`; `summary` truncated comment; `metadata.number`, `metadata.type="issue"`
- PR comments: same as above with `metadata.type="pull_request"`
- Reviews: `title` `reviewed PR #<number> <title>`; `summary` review state/body; `metadata.state`, `metadata.number`


## Date handling

- Use local timezone (consistent with current app) to determine date bounds; convert to ISO-8601 UTC for API calls
- For date ranges, the CLI already iterates day-by-day; reuse that to call `GithubRunner.run(date_header=True)` for each date


## Dependencies

- Option A (recommended): direct `requests` + lightweight GraphQL POST and REST calls
- Option B: `PyGithub` for REST, and manual GraphQL for contributions
- Start with Option A to minimize dependency complexity
- Add to `pyproject.toml` if needed (`requests`, optional `tenacity` for retries)


## Testing strategy (pytest)

- Unit tests under `tests/`:
  - `test_github_config.py`: env/CLI parsing → `GithubConfig`
  - `test_github_client_graphql.py`: map GraphQL results to `Change` objects
  - `test_github_client_rest.py`: map REST comments to `Change` objects
  - `test_github_runner.py`: happy path run() with mocked client returns; rendering smoke test
  - `test_cli_unified.py`: Typer CLI parsing for the unified command, include/exclude filters, org/repo filters, date/range; detection of active platforms
- Use `pytest` fixtures:
  - `monkeypatch` for env vars
  - sample JSON fixtures for GraphQL and REST responses
  - mock HTTP with `responses` (REST) and `responses`/`requests_mock` for GraphQL POST
- Edge cases:
  - empty results
  - pagination (multi-page REST)
  - rate limit backoff path when `--safe-rate` is set
  - enterprise custom URLs
  - include/exclude filters
- CI guidance:
  - fast, deterministic tests; no live API calls
  - optional `pytest -q` target and coverage threshold


## Atomic task breakdown

1) Scaffolding
   - Create `summarizer/github/` package with `__init__.py`
   - Add `GithubConfig` with env + CLI-parsed fields
   - Add `ChangeType` and `Change` to `common/models.py`
   - Commit: “feat(github): scaffold package, config, and common Change model”

2) Unified CLI integration
   - Make Webex auth flags optional; remove interactive prompts for Webex when absent
   - Add optional GitHub flags (token, URLs, filters)
   - Detect active platforms based on presence of credentials
   - Fail the run if any provided credentials are invalid
   - Commit: “feat(cli): single command with auto-detected platforms (webex, github)”

3) Console rendering
   - Add `display_changes` and `display_changes_summary` to `common/console_ui.py`
   - Commit: “feat(ui): render GitHub changes and summary”

4) GraphQL queries (contributions)
   - Implement POST to `graphql_url` with `viewer` and `contributionsCollection` queries
   - Map commits/issues/PRs/reviews to `Change`
   - Commit: “feat(github): GraphQL contributions mapping to Change”

5) REST fallbacks for comments
   - Implement REST calls for issue and PR comments with pagination
   - Respect `org_filters`/`repo_filters`
   - Commit: “feat(github): REST comment collection (issues/PRs)”

6) Runner
   - Implement `GithubRunner.run()` to orchestrate fetch, map, display
   - Add connection validation and identity resolution in `connect()`
   - Wire orchestrator in CLI to run Webex and/or GitHub on each date
   - Commit: “feat(github): add GithubRunner and orchestrated multi-platform run”

7) Filters & include/exclude
   - Apply repo/org filters and include/exclude types in client mapping stage
   - Commit: “feat(github): support include/exclude types and repo/org filters”

8) Rate limiting & retries
   - Respect `X-RateLimit-*` headers; implement polite backoff when `--safe-rate`
   - Add minimal retry on transient 5xx
   - Commit: “feat(github): rate limit awareness and retries”

9) Tests
   - Add unit tests and fixtures per Testing strategy
   - Add tests for unified CLI detection logic (none/one/both platforms; invalid creds)
   - Commit: “test(cli): unified CLI detection; test(github): config, client, runner”

10) Docs
   - Update `README.md` with Github usage examples (token, enterprise URLs, filters)
   - Commit: “docs: add GitHub usage and configuration”


## Developer guidance

- Prefer **atomic commits**: one logical change per commit; keep diffs small and focused
- Write precise commit messages with a short imperative subject and an optional body
- Maintain green tests; when adding a failing test for TDD, follow with a commit that fixes it
- Keep platform-specific code in `summarizer/github/` and reuse common helpers where sensible
- Avoid changing Webex behavior; GitHub integration should be additive
- Use type hints and follow the repo’s code style; run linters/formatters if configured


## Example pytest snippets

```python
# tests/test_cli_unified.py
from typer.testing import CliRunner
from summarizer.cli import app

def test_github_cli_parses_minimal(monkeypatch):
    runner = CliRunner()
    result = runner.invoke(
        app,
        [
            "--github-token", "t", 
            "--target-date", "2024-07-01",
        ],
    )
    assert result.exit_code == 0
```

```python
# tests/test_github_client_graphql.py
import json
import responses

def test_maps_contributions_to_changes(monkeypatch):
    # mock POST to graphql_url and assert Change objects are produced
    pass
```


## Acceptance criteria

- Unified `summarizer` command includes GitHub when credentials are provided and valid, against both GitHub.com and GHE (configurable URLs)
- Token-only configuration works; user is auto-resolved
- Date and date-range supported (day-by-day output)
- At least commits, issues, PRs, reviews rendered; comments included when REST fallback enabled
- Clear console tables and summary counts
- Unit tests for config, client mapping, runner, and CLI pass
- No regressions in Webex functionality


## Out of scope (initial version)

- Fine-grained branch-scoped commit filtering beyond repo constraints
- Full-text content rendering beyond short summaries
- Cross-day grouping of changes

