"""GitHub REST API client operations."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

import requests

from summarizer.common.models import Change, ChangeType
from summarizer.github.config import GithubConfig
from summarizer.github.utils import extract_number, parse_iso, parse_link_header

logger = logging.getLogger(__name__)


class RESTClient:
    """GitHub REST API client."""

    def __init__(self, config: GithubConfig) -> None:
        """Initialize with GitHub configuration."""
        self.config = config

    def fetch_comments(
        self,
        repos: set[str],
        start: datetime,
        end: datetime,
        viewer_login: str,
    ) -> list[Change]:
        """Fetch issue and PR comments from GitHub REST API."""
        results: list[Change] = []

        if ChangeType.ISSUE_COMMENT in set(self.config.include_types):
            results.extend(self._fetch_issue_comments(repos, start, end, viewer_login))

        if ChangeType.PR_COMMENT in set(self.config.include_types):
            results.extend(
                self._fetch_pr_review_comments(repos, start, end, viewer_login)
            )

        return results

    def _fetch_issue_comments(
        self,
        repos: set[str],
        start: datetime,
        end: datetime,
        viewer_login: str,
    ) -> list[Change]:
        """Fetch issue comments from REST API."""
        results: list[Change] = []
        headers = {
            "Authorization": f"Bearer {self.config.github_token}",
            "Accept": "application/vnd.github+json",
        }
        since = start.strftime("%Y-%m-%dT%H:%M:%SZ")

        for full in repos:
            owner, name = full.split("/", 1)
            url = f"{self.config.api_url}/repos/{owner}/{name}/issues/comments"
            next_url = f"{url}?since={since}"

            while next_url:
                resp = requests.get(next_url, headers=headers, timeout=60)
                if resp.status_code == 404:
                    logger.debug(f"Repository {full} not found or no access (404)")
                    break
                resp.raise_for_status()

                comments = resp.json() if isinstance(resp.json(), list) else []
                for comment in comments:
                    if comment.get("user", {}).get("login") != viewer_login:
                        continue

                    created_at = parse_iso(comment.get("created_at"))
                    if (
                        not created_at
                        or created_at < start.replace(tzinfo=UTC)
                        or created_at >= end.replace(tzinfo=UTC)
                    ):
                        continue

                    issue_url = comment.get("issue_url", "")
                    number = extract_number(issue_url)
                    title = (
                        f"Commented on issue #{number}" if number else "Issue comment"
                    )

                    results.append(
                        Change(
                            id=comment.get("html_url", ""),
                            type=ChangeType.ISSUE_COMMENT,
                            timestamp=created_at,
                            repo_full_name=full,
                            title=title,
                            url=comment.get("html_url", ""),
                            summary=comment.get("body", "")[:200]
                            if comment.get("body")
                            else None,
                            branch_name=None,  # Comments don't have associated branches
                            metadata={"number": number or "", "type": "issue"},
                        )
                    )

                next_url = parse_link_header(resp.headers.get("Link"))

        return results

    def _fetch_pr_review_comments(
        self,
        repos: set[str],
        start: datetime,
        end: datetime,
        viewer_login: str,
    ) -> list[Change]:
        """Fetch PR review comments from REST API."""
        results: list[Change] = []
        headers = {
            "Authorization": f"Bearer {self.config.github_token}",
            "Accept": "application/vnd.github+json",
        }
        since = start.strftime("%Y-%m-%dT%H:%M:%SZ")

        for full in repos:
            owner, name = full.split("/", 1)
            url = f"{self.config.api_url}/repos/{owner}/{name}/pulls/comments"
            next_url = f"{url}?since={since}"

            while next_url:
                resp = requests.get(next_url, headers=headers, timeout=60)
                if resp.status_code == 404:
                    logger.debug(f"Repository {full} not found or no access (404)")
                    break
                resp.raise_for_status()

                comments = resp.json() if isinstance(resp.json(), list) else []
                for comment in comments:
                    if comment.get("user", {}).get("login") != viewer_login:
                        continue

                    created_at = parse_iso(comment.get("created_at"))
                    if (
                        not created_at
                        or created_at < start.replace(tzinfo=UTC)
                        or created_at >= end.replace(tzinfo=UTC)
                    ):
                        continue

                    pr_url = comment.get("pull_request_url", "")
                    number = extract_number(pr_url)
                    title = f"Commented on PR #{number}" if number else "PR comment"

                    results.append(
                        Change(
                            id=comment.get("html_url", ""),
                            type=ChangeType.PR_COMMENT,
                            timestamp=created_at,
                            repo_full_name=full,
                            title=title,
                            url=comment.get("html_url", ""),
                            summary=comment.get("body", "")[:200]
                            if comment.get("body")
                            else None,
                            branch_name=None,  # Comments don't have associated branches
                            metadata={"number": number or "", "type": "pull_request"},
                        )
                    )

                next_url = parse_link_header(resp.headers.get("Link"))

        return results

    def fetch_detailed_commits(
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
        since = start.strftime("%Y-%m-%dT%H:%M:%SZ")

        for full in repos:
            owner, name = full.split("/", 1)
            url = f"{self.config.api_url}/repos/{owner}/{name}/commits"
            next_url = f"{url}?author={viewer_login}&since={since}"

            while next_url:
                resp = requests.get(next_url, headers=headers, timeout=60)
                if resp.status_code == 401:
                    raise ValueError("Unauthorized: invalid GitHub token")
                if resp.status_code == 404:
                    logger.debug(f"Repository {full} not found or no access (404)")
                    break
                resp.raise_for_status()

                commits = resp.json() if isinstance(resp.json(), list) else []
                for commit in commits:
                    commit_date_str = (
                        commit.get("commit", {}).get("author", {}).get("date")
                    )
                    commit_date = parse_iso(commit_date_str)

                    if not commit_date:
                        logger.debug(
                            f"Commit skipped - no valid date: {commit_date_str} "
                            f"(repo: {full}, sha: {commit.get('sha', 'unknown')[:7]})"
                        )
                        continue

                    # Filter by date range
                    if commit_date >= end:
                        logger.debug(
                            f"Commit filtered out by date: {commit_date} >= {end} "
                            f"(repo: {full}, sha: {commit.get('sha', 'unknown')[:7]})"
                        )
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

                    # Fetch branch information for this commit
                    branch_name = self._get_branch_for_commit(full, sha)

                    results.append(
                        Change(
                            id=html_url or f"commit-{full}-{sha}",
                            type=ChangeType.COMMIT,
                            timestamp=commit_date,
                            repo_full_name=full,
                            title=title,
                            url=html_url,
                            summary=message_headline if message_headline else None,
                            branch_name=branch_name,
                            metadata=metadata,
                        )
                    )

                next_url = parse_link_header(resp.headers.get("Link"))

        return results

    def _get_branch_for_commit(
        self, full_repo_name: str, commit_sha: str
    ) -> str | None:
        """Get the branch name associated with a commit using GitHub REST API."""
        if not commit_sha:
            return None

        headers = {
            "Authorization": f"Bearer {self.config.github_token}",
            "Accept": "application/vnd.github+json",
        }

        owner, name = full_repo_name.split("/", 1)

        # First, try to find branches where this commit is the HEAD
        try:
            url = f"{self.config.api_url}/repos/{owner}/{name}/commits/{commit_sha}/branches-where-head"
            resp = requests.get(url, headers=headers, timeout=60)
            if resp.status_code == 200:
                branches = resp.json() if isinstance(resp.json(), list) else []
                if branches:
                    branch_name = branches[0].get("name")
                    logger.debug(
                        f"Found branch '{branch_name}' where commit {commit_sha[:7]} is HEAD in {full_repo_name}"
                    )
                    return branch_name
        except requests.RequestException as e:
            logger.debug(
                f"Failed to check branches-where-head for commit {commit_sha[:7]} in {full_repo_name}: {e}"
            )

        # If commit is not HEAD of any branch, try to find it in the default branch
        try:
            # Get repository info to find default branch
            repo_url = f"{self.config.api_url}/repos/{owner}/{name}"
            repo_resp = requests.get(repo_url, headers=headers, timeout=60)
            if repo_resp.status_code == 200:
                repo_data = repo_resp.json()
                default_branch = repo_data.get("default_branch", "main")

                # Check if commit exists in default branch using compare API
                compare_url = f"{self.config.api_url}/repos/{owner}/{name}/compare/{commit_sha}...{default_branch}"
                compare_resp = requests.get(compare_url, headers=headers, timeout=60)
                if compare_resp.status_code == 200:
                    compare_data = compare_resp.json()
                    # If status is 'behind' or 'identical', the commit is in the default branch
                    status = compare_data.get("status")
                    if status in ["behind", "identical"]:
                        logger.debug(
                            f"Found commit {commit_sha[:7]} in default branch '{default_branch}' in {full_repo_name}"
                        )
                        return default_branch
        except requests.RequestException as e:
            logger.debug(
                f"Failed to check default branch for commit {commit_sha[:7]} in {full_repo_name}: {e}"
            )

        # If all else fails, try to get the associated pull request
        try:
            # Search for pull requests associated with this commit
            search_url = f"{self.config.api_url}/search/issues"
            search_params = {
                "q": f"repo:{full_repo_name} type:pr {commit_sha}",
                "sort": "created",
                "order": "desc",
            }
            search_resp = requests.get(
                search_url, headers=headers, params=search_params, timeout=60
            )
            if search_resp.status_code == 200:
                search_data = search_resp.json()
                items = search_data.get("items", [])
                if items:
                    # Get the first PR and extract branch info from it
                    pr = items[0]
                    pr_number = pr.get("number")
                    if pr_number:
                        pr_url = f"{self.config.api_url}/repos/{owner}/{name}/pulls/{pr_number}"
                        pr_resp = requests.get(pr_url, headers=headers, timeout=60)
                        if pr_resp.status_code == 200:
                            pr_data = pr_resp.json()
                            head_ref = pr_data.get("head", {}).get("ref")
                            if head_ref:
                                logger.debug(
                                    f"Found commit {commit_sha[:7]} in PR branch '{head_ref}' in {full_repo_name}"
                                )
                                return head_ref
        except requests.RequestException as e:
            logger.debug(
                f"Failed to search for PR associated with commit {commit_sha[:7]} in {full_repo_name}: {e}"
            )

        logger.debug(
            f"Could not determine branch for commit {commit_sha[:7]} in {full_repo_name}"
        )
        return None

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
