"""GitHub API client (skeleton).

Provides typed methods that will be easy to unit-test. Actual HTTP will be
implemented in a later task along with GraphQL/REST mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests

from summarizer.common.models import Change, ChangeType
from summarizer.github.config import GithubConfig


@dataclass
class Identity:
    """Authenticated GitHub identity information."""

    login: str


class GithubClient:
    """Thin client around GitHub GraphQL/REST.

    This class intentionally avoids importing requests for now to keep the
    scaffolding atomic and easily testable with pure unit tests. HTTP will be
    added alongside tests that mock network calls.
    """

    def __init__(self, config: GithubConfig) -> None:
        """Initialize the client with a `GithubConfig`."""
        self.config = config

    # Connection / identity
    def get_viewer(self) -> Identity:
        """Return authenticated identity. Raises on authentication failure."""
        if not self.config.github_token:
            raise ValueError("Missing GitHub token")
        headers = {
            "Authorization": f"Bearer {self.config.github_token}",
            "Accept": "application/json",
        }
        query = "query { viewer { login } }"
        resp = requests.post(
            self.config.graphql_url,
            json={"query": query},
            headers=headers,
            timeout=30,
        )
        if resp.status_code == 401:
            raise ValueError("Unauthorized: invalid GitHub token")
        data: dict[str, Any] = resp.json()
        # GraphQL may respond with 200 and errors
        if "errors" in data and data["errors"]:
            # surface first error message if present
            msg = data["errors"][0].get("message", "GraphQL error")
            raise ValueError(f"GitHub GraphQL error: {msg}")
        login = data.get("data", {}).get("viewer", {}).get("login")
        if not login:
            raise ValueError("Unable to resolve viewer login from GraphQL response")
        return Identity(login=login)

    # Activity collection
    def get_changes(self, start: datetime, end: datetime) -> list[Change]:
        """Return changes between [start, end)."""
        if not self.config.github_token:
            return []
        data = self._fetch_contributions(start, end)
        user = data.get("data", {}).get("user", {})
        coll = user.get("contributionsCollection", {})
        changes: list[Change] = []
        changes.extend(self._collect_issues(coll))
        changes.extend(self._collect_pull_requests(coll))
        changes.extend(self._collect_reviews(coll))
        changes.extend(self._collect_commits(coll))

        # REST fallbacks for comments (issue comments and PR review comments)
        repos = self._discover_repos_from_contributions(coll)
        repos.update(self.config.repo_filters or [])
        viewer_login = self.config.user or self.get_viewer().login
        if ChangeType.ISSUE_COMMENT in set(self.config.include_types):
            changes.extend(self._fetch_issue_comments(repos, start, end, viewer_login))
        if ChangeType.PR_COMMENT in set(self.config.include_types):
            changes.extend(
                self._fetch_pr_review_comments(repos, start, end, viewer_login)
            )
        changes.sort(key=lambda ch: ch.timestamp)
        return changes

    def _fetch_contributions(self, start: datetime, end: datetime) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.config.github_token}",
            "Accept": "application/json",
        }
        query = (
            "query($login:String!, $from:DateTime!, $to:DateTime!) {\n"
            "  user(login:$login) {\n"
            "    contributionsCollection(from:$from, to:$to) {\n"
            "      issueContributions(first: 100) { nodes {\n"
            "        occurredAt\n"
            "        issue { title url createdAt repository { nameWithOwner } }\n"
            "      }}\n"
            "      pullRequestContributions(first: 100) { nodes {\n"
            "        occurredAt\n"
            "        pullRequest { title url createdAt repository { nameWithOwner } }\n"
            "      }}\n"
            "      pullRequestReviewContributions(first: 100) { nodes {\n"
            "        occurredAt\n"
            "        pullRequest { title url createdAt repository { nameWithOwner } }\n"
            "      }}\n"
            "      commitContributionsByRepository(maxRepositories: 20) {\n"
            "        repository { nameWithOwner }\n"
            "        contributions(first: 100) { nodes {\n"
            "          occurredAt\n"
            "          commit { messageHeadline url oid }\n"
            "        }}\n"
            "      }\n"
            "    }\n"
            "  }\n"
            "}\n"
        )
        user_login = self.config.user or self.get_viewer().login
        variables = {
            "login": user_login,
            "from": self.to_utc_iso(start),
            "to": self.to_utc_iso(end),
        }
        resp = requests.post(
            self.config.graphql_url,
            json={"query": query, "variables": variables},
            headers=headers,
            timeout=60,
        )
        data: dict[str, Any] = resp.json()
        if resp.status_code == 401:
            raise ValueError("Unauthorized: invalid GitHub token")
        if "errors" in data and data["errors"]:
            msg = data["errors"][0].get("message", "GraphQL error")
            raise ValueError(f"GitHub GraphQL error: {msg}")
        return data

    def _collect_issues(self, coll: dict[str, Any]) -> list[Change]:
        if ChangeType.ISSUE not in set(self.config.include_types):
            return []
        results: list[Change] = []
        for node in coll.get("issueContributions", {}).get("nodes", []):
            issue = node.get("issue")
            if not issue:
                continue
            repo = issue.get("repository", {}).get("nameWithOwner")
            if not self._repo_allowed(repo):
                continue
            ts = self._parse_iso(node.get("occurredAt") or issue.get("createdAt"))
            if ts is None:
                continue
            results.append(
                Change(
                    id=issue.get("url", "") or f"issue-{repo}-{ts.isoformat()}",
                    type=ChangeType.ISSUE,
                    timestamp=ts,
                    repo_full_name=repo or "",
                    title=issue.get("title", ""),
                    url=issue.get("url", ""),
                )
            )
        return results

    def _collect_pull_requests(self, coll: dict[str, Any]) -> list[Change]:
        if ChangeType.PULL_REQUEST not in set(self.config.include_types):
            return []
        results: list[Change] = []
        for node in coll.get("pullRequestContributions", {}).get("nodes", []):
            pr = node.get("pullRequest")
            if not pr:
                continue
            repo = pr.get("repository", {}).get("nameWithOwner")
            if not self._repo_allowed(repo):
                continue
            ts = self._parse_iso(node.get("occurredAt") or pr.get("createdAt"))
            if ts is None:
                continue
            results.append(
                Change(
                    id=pr.get("url", "") or f"pr-{repo}-{ts.isoformat()}",
                    type=ChangeType.PULL_REQUEST,
                    timestamp=ts,
                    repo_full_name=repo or "",
                    title=pr.get("title", ""),
                    url=pr.get("url", ""),
                )
            )
        return results

    def _collect_reviews(self, coll: dict[str, Any]) -> list[Change]:
        if ChangeType.REVIEW not in set(self.config.include_types):
            return []
        results: list[Change] = []
        for node in coll.get("pullRequestReviewContributions", {}).get("nodes", []):
            pr = node.get("pullRequest")
            if not pr:
                continue
            repo = pr.get("repository", {}).get("nameWithOwner")
            if not self._repo_allowed(repo):
                continue
            ts = self._parse_iso(node.get("occurredAt") or pr.get("createdAt"))
            if ts is None:
                continue
            results.append(
                Change(
                    id=pr.get("url", "") or f"review-{repo}-{ts.isoformat()}",
                    type=ChangeType.REVIEW,
                    timestamp=ts,
                    repo_full_name=repo or "",
                    title=f"Reviewed: {pr.get('title', '')}",
                    url=pr.get("url", ""),
                )
            )
        return results

    def _collect_commits(self, coll: dict[str, Any]) -> list[Change]:
        if ChangeType.COMMIT not in set(self.config.include_types):
            return []
        results: list[Change] = []
        for repo_contrib in coll.get("commitContributionsByRepository", []):
            repo = repo_contrib.get("repository", {}).get("nameWithOwner")
            if not self._repo_allowed(repo):
                continue
            for cnode in repo_contrib.get("contributions", {}).get("nodes", []):
                ts = self._parse_iso(cnode.get("occurredAt"))
                commit = cnode.get("commit", {})
                if ts is None or not commit:
                    continue
                results.append(
                    Change(
                        id=commit.get("oid", ""),
                        type=ChangeType.COMMIT,
                        timestamp=ts,
                        repo_full_name=repo or "",
                        title=commit.get("messageHeadline", ""),
                        url=commit.get("url", ""),
                        metadata={"sha": commit.get("oid", "")},
                    )
                )
        return results

    def _discover_repos_from_contributions(self, coll: dict[str, Any]) -> set[str]:
        return set(self._iter_repo_names(coll))

    @staticmethod
    def _iter_repo_names(coll: dict[str, Any]) -> list[str]:
        repos: list[str] = []
        # Nodes that contain an inner object with repository
        containers = [
            ("issueContributions", "issue"),
            ("pullRequestContributions", "pullRequest"),
            ("pullRequestReviewContributions", "pullRequest"),
        ]
        for container_key, inner_key in containers:
            for node in coll.get(container_key, {}).get("nodes", []):
                obj = node.get(inner_key) or {}
                repo = (obj.get("repository") or {}).get("nameWithOwner")
                if repo:
                    repos.append(repo)
        for repo_contrib in coll.get("commitContributionsByRepository", []):
            repo = (repo_contrib.get("repository") or {}).get("nameWithOwner")
            if repo:
                repos.append(repo)
        return repos

    def _fetch_issue_comments(
        self,
        repos: set[str],
        start: datetime,
        end: datetime,
        viewer_login: str,
    ) -> list[Change]:
        return self._fetch_comments(
            repos=repos,
            start=start,
            end=end,
            viewer_login=viewer_login,
            resource="issues/comments",
            url_field="issue_url",
            change_type=ChangeType.ISSUE_COMMENT,
            label="issue",
        )

    def _fetch_pr_review_comments(
        self,
        repos: set[str],
        start: datetime,
        end: datetime,
        viewer_login: str,
    ) -> list[Change]:
        return self._fetch_comments(
            repos=repos,
            start=start,
            end=end,
            viewer_login=viewer_login,
            resource="pulls/comments",
            url_field="pull_request_url",
            change_type=ChangeType.PR_COMMENT,
            label="PR",
        )

    @staticmethod
    def _next_link(link_header: str | None) -> str | None:
        if not link_header:
            return None
        # Minimal RFC5988 Link header parser for rel="next"
        parts = link_header.split(",")
        for p in parts:
            if 'rel="next"' in p:
                start = p.find("<")
                end = p.find(">", start + 1)
                if start != -1 and end != -1:
                    return p[start + 1 : end]
        return None

    @staticmethod
    def _extract_number(api_url: str | None) -> str | None:
        if not api_url:
            return None
        try:
            # Issue URL ends with /issues/{number} or PR URL with /pulls/{number}
            return api_url.rstrip("/").split("/")[-1]
        except Exception:
            return None

    @staticmethod
    def _ensure_utc(dt: datetime) -> datetime:
        if dt.tzinfo is None:
            return dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC)

    # ---------------
    # Helper methods
    # ---------------
    def _repo_allowed(self, full_name: str | None) -> bool:
        if not full_name:
            return False
        if self.config.repo_filters:
            return full_name in set(self.config.repo_filters)
        if self.config.org_filters:
            owner = full_name.split("/", 1)[0]
            return owner in set(self.config.org_filters)
        return True

    @staticmethod
    def _parse_iso(value: str | None) -> datetime | None:
        if not value:
            return None
        try:
            # GraphQL returns ISO-8601; datetime.fromisoformat supports Z via replace
            v = value.replace("Z", "+00:00")
            return datetime.fromisoformat(v)
        except Exception:
            return None

    @staticmethod
    def _ct(name: str) -> ChangeType:
        return ChangeType[name]

    # Utilities
    @staticmethod
    def to_utc_iso(dt: datetime) -> str:
        """Convert a datetime to an ISO-8601 UTC string."""
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).isoformat()
