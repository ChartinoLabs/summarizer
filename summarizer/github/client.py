"""GitHub API client - refactored with focused responsibilities."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

import requests

from summarizer.common.models import Change, ChangeType
from summarizer.github.config import GithubConfig
from summarizer.github.graphql import GraphQLClient
from summarizer.github.rest import RESTClient

logger = logging.getLogger(__name__)


@dataclass
class Identity:
    """Authenticated GitHub identity information."""

    login: str


class GithubClient:
    """Main GitHub API client orchestrator.

    Coordinates between GraphQL and REST clients to provide a unified interface
    for fetching GitHub changes and activity data.
    """

    def __init__(self, config: GithubConfig) -> None:
        """Initialize the client with a GithubConfig."""
        self.config = config
        self.graphql_client = GraphQLClient(config)
        self.rest_client = RESTClient(config)

    def get_viewer(self) -> Identity:
        """Return authenticated identity. Raises on authentication failure."""
        if not self.config.github_token:
            raise ValueError("Missing GitHub token")

        headers = {
            "Authorization": f"Bearer {self.config.github_token}",
            "Accept": "application/json",
        }
        query = "query { viewer { login } }"
        graphql_url = self.config.graphql_url or f"{self.config.api_url}/graphql"

        resp = requests.post(
            graphql_url, json={"query": query}, headers=headers, timeout=60
        )
        if resp.status_code == 401:
            raise ValueError("Unauthorized: Invalid GitHub token")
        resp.raise_for_status()
        data = resp.json()

        # GraphQL may respond with 200 and errors
        if "errors" in data and data["errors"]:
            # surface first error message if present
            msg = data["errors"][0].get("message", "GraphQL error")
            raise ValueError(f"GitHub GraphQL error: {msg}")

        login = data.get("data", {}).get("viewer", {}).get("login")
        if not login:
            raise ValueError("Unable to resolve viewer login from GraphQL response")

        return Identity(login=login)

    def get_changes(self, start: datetime, end: datetime) -> list[Change]:
        """Return changes between [start, end)."""
        if not self.config.github_token:
            return []

        logger.info("GitHub window start=%s end=%s", start, end)
        logger.info(
            "GitHub include_types=%s org_filters=%s repo_filters=%s",
            sorted(t.name for t in self.config.include_types),
            self.config.org_filters,
            self.config.repo_filters,
        )

        # Fetch contributions via GraphQL
        coll = self.graphql_client.fetch_contributions(start, end)

        # Log summary of GraphQL collections returned
        self._log_contributions_summary(coll)

        # Collect changes from GraphQL data
        changes: list[Change] = []
        changes.extend(self.graphql_client.collect_issues(coll))
        changes.extend(self.graphql_client.collect_pull_requests(coll))
        changes.extend(self.graphql_client.collect_reviews(coll))
        changes.extend(self.graphql_client.collect_commits(coll))

        # Get repositories for REST API calls
        repos = self.graphql_client.discover_repos_from_contributions(coll)
        repos.update(self.config.repo_filters or [])
        logger.info(
            "GitHub repos to scan for comments and commits (count=%d): %s",
            len(repos),
            sorted(repos),
        )

        viewer_login = self.config.user or self.get_viewer().login

        # Fetch detailed commit information via REST API
        if ChangeType.COMMIT in set(self.config.include_types):
            # Replace basic commit data with detailed commit data
            changes = [c for c in changes if c.type != ChangeType.COMMIT]
            changes.extend(
                self.rest_client.fetch_detailed_commits(repos, start, end, viewer_login)
            )

        # Fetch comments via REST API
        changes.extend(self.rest_client.fetch_comments(repos, start, end, viewer_login))

        # Sort by timestamp and log summary
        changes.sort(key=lambda ch: ch.timestamp)
        self._log_changes_summary(changes)

        return changes

    def _log_contributions_summary(self, coll: dict) -> None:
        """Log summary of GraphQL contributions collection."""
        issues_count = len(coll.get("issueContributions", {}).get("nodes", []))
        prs_count = len(coll.get("pullRequestContributions", {}).get("nodes", []))
        reviews_count = len(
            coll.get("pullRequestReviewContributions", {}).get("nodes", [])
        )
        commits_repo_count = len(coll.get("commitContributionsByRepository", []))
        restricted = coll.get("restrictedContributionsCount")

        logger.debug("GraphQL contributionsCollection analysis:")
        logger.debug(
            f"  Contribution counts: issues={issues_count}, prs={prs_count}, "
            f"reviews={reviews_count}, commit_repos={commits_repo_count}, "
            f"restricted={restricted}"
        )

        # Log detailed commit contribution info for debugging
        for i, repo_contrib in enumerate(
            coll.get("commitContributionsByRepository", []), 1
        ):
            repo_name = repo_contrib.get("repository", {}).get(
                "nameWithOwner", "unknown"
            )
            contrib_count = repo_contrib.get("contributions", {}).get("totalCount", 0)
            logger.debug(
                f"  Commit repo {i}: {repo_name} ({contrib_count} contributions)"
            )

            # Log individual contribution timestamps for debugging
            for j, contrib in enumerate(
                repo_contrib.get("contributions", {}).get("nodes", [])[:2], 1
            ):  # Limit to first 2 for brevity
                occurred_at = contrib.get("occurredAt")
                logger.debug(f"    Contribution {j} occurredAt: {occurred_at}")

    def _log_changes_summary(self, changes: list[Change]) -> None:
        """Log summary of collected changes."""
        counts: dict[str, int] = {}
        for c in changes:
            counts[c.type.value] = counts.get(c.type.value, 0) + 1

        logger.info(
            "GitHub changes collected: total=%d by_type=%s", len(changes), counts
        )
