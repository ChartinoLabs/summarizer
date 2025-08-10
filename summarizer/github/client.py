"""GitHub API client (skeleton).

Provides typed methods that will be easy to unit-test. Actual HTTP will be
implemented in a later task along with GraphQL/REST mapping.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import requests

from summarizer.common.models import Change, ChangeType
from summarizer.github.config import GithubConfig

logger = logging.getLogger(__name__)


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
        logger.info("GitHub window start=%s end=%s", start, end)
        logger.info(
            "GitHub include_types=%s org_filters=%s repo_filters=%s",
            sorted(t.name for t in self.config.include_types),
            self.config.org_filters,
            self.config.repo_filters,
        )
        data = self._fetch_contributions(start, end)
        user = data.get("data", {}).get("user", {})
        coll = user.get("contributionsCollection", {})
        # Log quick summary of GraphQL collections returned
        issues_count = len(coll.get("issueContributions", {}).get("nodes", []))
        prs_count = len(coll.get("pullRequestContributions", {}).get("nodes", []))
        reviews_count = len(
            coll.get("pullRequestReviewContributions", {}).get("nodes", [])
        )
        commits_repo_count = len(coll.get("commitContributionsByRepository", []))
        restricted = coll.get("restrictedContributionsCount")
        logger.info(
            "GraphQL collections: issues=%d prs=%d reviews=%d",
            issues_count,
            prs_count,
            reviews_count,
        )
        logger.info(
            "GraphQL collections: commitRepos=%d restricted=%s",
            commits_repo_count,
            restricted,
        )
        changes: list[Change] = []
        changes.extend(self._collect_issues(coll))
        changes.extend(self._collect_pull_requests(coll))
        changes.extend(self._collect_reviews(coll))
        changes.extend(self._collect_commits(coll))

        # REST fallbacks for comments and detailed commit info
        repos = self._discover_repos_from_contributions(coll)
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
                self._fetch_detailed_commits(repos, start, end, viewer_login)
            )

        if ChangeType.ISSUE_COMMENT in set(self.config.include_types):
            changes.extend(self._fetch_issue_comments(repos, start, end, viewer_login))
        if ChangeType.PR_COMMENT in set(self.config.include_types):
            changes.extend(
                self._fetch_pr_review_comments(repos, start, end, viewer_login)
            )
        changes.sort(key=lambda ch: ch.timestamp)
        # Summarize counts by type
        counts: dict[str, int] = {}
        for c in changes:
            counts[c.type.value] = counts.get(c.type.value, 0) + 1
        logger.info(
            "GitHub changes collected: total=%d by_type=%s", len(changes), counts
        )
        return changes

    def _fetch_contributions(self, start: datetime, end: datetime) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self.config.github_token}",
            "Accept": "application/json",
        }
        query = (
            "query($login:String!, $from:DateTime!, $to:DateTime!) {\n"
            "  user(login:$login) {\n"
            "    contributionsCollection(\n"
            "      from:$from, to:$to\n"
            "    ) {\n"
            "      hasAnyRestrictedContributions\n"
            "      restrictedContributionsCount\n"
            "      issueContributions(first: 100) { totalCount nodes {\n"
            "        occurredAt\n"
            "        issue { title url createdAt repository { nameWithOwner } }\n"
            "      }}\n"
            "      pullRequestContributions(first: 100) { totalCount nodes {\n"
            "        occurredAt\n"
            "        pullRequest { title url createdAt repository { nameWithOwner } }\n"
            "      }}\n"
            "      pullRequestReviewContributions(first: 100) { totalCount nodes {\n"
            "        occurredAt\n"
            "        pullRequest { title url createdAt repository { nameWithOwner } }\n"
            "      }}\n"
            "      commitContributionsByRepository(maxRepositories: 20) {\n"
            "        repository { nameWithOwner }\n"
            "        contributions(first: 100) { nodes {\n"
            "          occurredAt\n"
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
        logger.info(
            "GraphQL vars: login=%s from=%s to=%s",
            variables["login"],
            variables["from"],
            variables["to"],
        )
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
        # This method now just returns empty since we fetch detailed commits via REST
        return []

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

    def _fetch_comments(
        self,
        *,
        repos: set[str],
        start: datetime,
        end: datetime,
        viewer_login: str,
        resource: str,
        url_field: str,
        change_type: ChangeType,
        label: str,
    ) -> list[Change]:
        results: list[Change] = []
        headers = {
            "Authorization": f"Bearer {self.config.github_token}",
            "Accept": "application/vnd.github+json",
        }
        start_utc = self._ensure_utc(start)
        end_utc = self._ensure_utc(end)
        since = self.to_utc_iso(start_utc)
        for full in repos:
            owner, name = full.split("/", 1)
            url = f"{self.config.api_url}/repos/{owner}/{name}/{resource}"
            next_url = f"{url}?since={since}"
            while next_url:
                resp = requests.get(next_url, headers=headers, timeout=60)
                if resp.status_code == 401:
                    raise ValueError("Unauthorized: invalid GitHub token")
                items = resp.json() if isinstance(resp.json(), list) else []
                for it in items:
                    created = self._parse_iso(it.get("created_at"))
                    if not created or not (start_utc <= created < end_utc):
                        continue
                    user = (it.get("user") or {}).get("login")
                    if user != viewer_login:
                        continue
                    ref_url = it.get(url_field, "")
                    num = self._extract_number(ref_url)
                    title = (
                        f"Commented on {label} #{num}"
                        if num
                        else f"Commented on {label}"
                    )
                    results.append(
                        Change(
                            id=str(it.get("id", "")),
                            type=change_type,
                            timestamp=created,
                            repo_full_name=full,
                            title=title,
                            url=it.get("html_url", ""),
                        )
                    )
                next_url = self._next_link(resp.headers.get("Link"))
        return results

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

    def _fetch_detailed_commits(
        self,
        repos: set[str],
        start: datetime,
        end: datetime,
        viewer_login: str,
    ) -> list[Change]:
        """Fetch detailed commit information via REST API."""
        results: list[Change] = []
        headers = {
            "Authorization": f"Bearer {self.config.github_token}",
            "Accept": "application/vnd.github+json",
        }
        start_utc = self._ensure_utc(start)
        end_utc = self._ensure_utc(end)
        since = self.to_utc_iso(start_utc)

        for full in repos:
            owner, name = full.split("/", 1)
            # Get commits for the specific author and time range
            url = f"{self.config.api_url}/repos/{owner}/{name}/commits"
            next_url = f"{url}?author={viewer_login}&since={since}"

            while next_url:
                resp = requests.get(next_url, headers=headers, timeout=60)
                if resp.status_code == 401:
                    raise ValueError("Unauthorized: invalid GitHub token")
                if resp.status_code == 404:
                    # Repository might not exist or no access
                    break

                commits = resp.json() if isinstance(resp.json(), list) else []
                for commit in commits:
                    commit_date_str = (
                        commit.get("commit", {}).get("author", {}).get("date")
                    )
                    commit_date = self._parse_iso(commit_date_str)

                    if not commit_date or not (start_utc <= commit_date < end_utc):
                        continue

                    # Extract commit details
                    commit_data = commit.get("commit", {})
                    message = commit_data.get("message", "")
                    message_headline = message.split("\n")[0] if message else ""
                    sha = commit.get("sha", "")
                    html_url = commit.get("html_url", "")

                    # Use the first line of the commit message as the title
                    if message_headline:
                        title = message_headline
                    elif sha:
                        title = f"Commit {sha[:7]}"
                    else:
                        title = "Commit"

                    # Store additional metadata
                    metadata = {}
                    if sha:
                        metadata["sha"] = sha[:7]  # Short SHA
                        metadata["full_sha"] = sha

                    results.append(
                        Change(
                            id=html_url or f"commit-{full}-{sha}",
                            type=ChangeType.COMMIT,
                            timestamp=commit_date,
                            repo_full_name=full,
                            title=title,
                            url=html_url,
                            summary=message_headline if message_headline else None,
                            metadata=metadata,
                        )
                    )

                next_url = self._next_link(resp.headers.get("Link"))

        return results

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
