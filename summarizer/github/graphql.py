"""GitHub GraphQL client operations."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import requests

from summarizer.common.models import Change, ChangeType
from summarizer.github.config import GithubConfig
from summarizer.github.utils import parse_iso

logger = logging.getLogger(__name__)


class GraphQLClient:
    """GitHub GraphQL API client."""

    def __init__(self, config: GithubConfig) -> None:
        """Initialize with GitHub configuration."""
        self.config = config

    def fetch_contributions(self, start: datetime, end: datetime) -> dict[str, Any]:
        """Fetch user contributions from GitHub GraphQL API."""
        user = self.config.user or "viewer"
        headers = {
            "Authorization": f"Bearer {self.config.github_token}",
            "Accept": "application/json",
        }
        from_date = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        to_date = end.strftime("%Y-%m-%dT%H:%M:%SZ")

        if user == "viewer":
            user_query_fragment = "viewer"
        else:
            user_query_fragment = f'user(login: "{user}")'

        query = f"""
        query {{
            {user_query_fragment} {{
                contributionsCollection(from: "{from_date}", to: "{to_date}") {{
                    totalCommitContributions
                    totalIssueContributions
                    totalPullRequestContributions
                    totalPullRequestReviewContributions
                    totalRepositoryContributions
                    restrictedContributionsCount
                    commitContributionsByRepository {{
                        contributions {{
                            totalCount
                        }}
                        repository {{
                            nameWithOwner
                        }}
                    }}
                    issueContributions(first: 50) {{
                        nodes {{
                            issue {{
                                title
                                number
                                url
                                createdAt
                                repository {{
                                    nameWithOwner
                                }}
                            }}
                        }}
                    }}
                    pullRequestContributions(first: 50) {{
                        nodes {{
                            pullRequest {{
                                title
                                number
                                url
                                createdAt
                                repository {{
                                    nameWithOwner
                                }}
                            }}
                        }}
                    }}
                    pullRequestReviewContributions(first: 50) {{
                        nodes {{
                            pullRequestReview {{
                                pullRequest {{
                                    title
                                    number
                                    url
                                    repository {{
                                        nameWithOwner
                                    }}
                                }}
                                createdAt
                                state
                            }}
                        }}
                    }}
                }}
            }}
        }}
        """
        graphql_url = self.config.graphql_url or f"{self.config.api_url}/graphql"
        resp = requests.post(
            graphql_url, json={"query": query}, headers=headers, timeout=60
        )
        resp.raise_for_status()
        data = resp.json()

        if "errors" in data:
            raise ValueError(f"GraphQL errors: {data['errors']}")

        user_key = "viewer" if user == "viewer" else "user"
        return data["data"][user_key]["contributionsCollection"]

    def collect_issues(self, coll: dict[str, Any]) -> list[Change]:
        """Extract issues from GraphQL contributions collection."""
        results: list[Change] = []
        issue_contribs = coll.get("issueContributions", {}).get("nodes", [])

        for contrib in issue_contribs:
            issue = contrib.get("issue", {})
            repo = issue.get("repository", {}).get("nameWithOwner", "")
            if not self._repo_allowed(repo):
                continue

            timestamp = parse_iso(issue.get("createdAt"))
            if not timestamp:
                continue

            results.append(
                Change(
                    id=issue.get("url", ""),
                    type=ChangeType.ISSUE,
                    timestamp=timestamp,
                    repo_full_name=repo,
                    title=issue.get("title", ""),
                    url=issue.get("url", ""),
                    summary=None,
                    metadata={"number": str(issue.get("number", ""))},
                )
            )

        return results

    def collect_pull_requests(self, coll: dict[str, Any]) -> list[Change]:
        """Extract pull requests from GraphQL contributions collection."""
        results: list[Change] = []
        pr_contribs = coll.get("pullRequestContributions", {}).get("nodes", [])

        for contrib in pr_contribs:
            pr = contrib.get("pullRequest", {})
            repo = pr.get("repository", {}).get("nameWithOwner", "")
            if not self._repo_allowed(repo):
                continue

            timestamp = parse_iso(pr.get("createdAt"))
            if not timestamp:
                continue

            results.append(
                Change(
                    id=pr.get("url", ""),
                    type=ChangeType.PULL_REQUEST,
                    timestamp=timestamp,
                    repo_full_name=repo,
                    title=pr.get("title", ""),
                    url=pr.get("url", ""),
                    summary=None,
                    metadata={"number": str(pr.get("number", ""))},
                )
            )

        return results

    def collect_reviews(self, coll: dict[str, Any]) -> list[Change]:
        """Extract pull request reviews from GraphQL contributions collection."""
        results: list[Change] = []
        review_contribs = coll.get("pullRequestReviewContributions", {}).get(
            "nodes", []
        )

        for contrib in review_contribs:
            review = contrib.get("pullRequestReview", {})
            pr = review.get("pullRequest", {})
            repo = pr.get("repository", {}).get("nameWithOwner", "")
            if not self._repo_allowed(repo):
                continue

            timestamp = parse_iso(review.get("createdAt"))
            if not timestamp:
                continue

            pr_title = pr.get("title", "")
            pr_number = pr.get("number", "")
            title = f"Reviewed: {pr_title}"

            results.append(
                Change(
                    id=f"{pr.get('url', '')}/reviews",
                    type=ChangeType.REVIEW,
                    timestamp=timestamp,
                    repo_full_name=repo,
                    title=title,
                    url=pr.get("url", ""),
                    summary=f"Review state: {review.get('state', 'UNKNOWN')}",
                    metadata={
                        "number": str(pr_number),
                        "state": review.get("state", ""),
                        "type": "pull_request",
                    },
                )
            )

        return results

    def collect_commits(self, coll: dict[str, Any]) -> list[Change]:
        """Extract commits from GraphQL contributions collection (basic info only)."""
        # Note: GraphQL contributions collection doesn't provide detailed commit info
        # This method is kept for completeness but detailed commits come from REST API
        return []

    def discover_repos_from_contributions(self, coll: dict[str, Any]) -> set[str]:
        """Extract repository names from contributions collection."""
        repos: set[str] = set()

        # From commit contributions
        for repo_contrib in coll.get("commitContributionsByRepository", []):
            repo_name = repo_contrib.get("repository", {}).get("nameWithOwner")
            if repo_name and self._repo_allowed(repo_name):
                repos.add(repo_name)

        # From issues
        for contrib in coll.get("issueContributions", {}).get("nodes", []):
            repo_name = (
                contrib.get("issue", {}).get("repository", {}).get("nameWithOwner")
            )
            if repo_name and self._repo_allowed(repo_name):
                repos.add(repo_name)

        # From pull requests
        for contrib in coll.get("pullRequestContributions", {}).get("nodes", []):
            repo_name = (
                contrib.get("pullRequest", {})
                .get("repository", {})
                .get("nameWithOwner")
            )
            if repo_name and self._repo_allowed(repo_name):
                repos.add(repo_name)

        # From reviews
        for contrib in coll.get("pullRequestReviewContributions", {}).get("nodes", []):
            repo_name = (
                contrib.get("pullRequestReview", {})
                .get("pullRequest", {})
                .get("repository", {})
                .get("nameWithOwner")
            )
            if repo_name and self._repo_allowed(repo_name):
                repos.add(repo_name)

        return repos

    def _repo_allowed(self, full_name: str | None) -> bool:
        """Check if repository is allowed by configuration filters."""
        if not full_name:
            return False
        if self.config.repo_filters:
            return full_name in set(self.config.repo_filters)
        if self.config.org_filters:
            owner = full_name.split("/")[0] if "/" in full_name else ""
            return owner in set(self.config.org_filters)
        return True
