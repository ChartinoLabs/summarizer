"""Tests for REST comment fallbacks in GithubClient."""

from datetime import datetime

import responses

from summarizer.common.models import ChangeType
from summarizer.github.client import GithubClient
from summarizer.github.config import GithubConfig


@responses.activate
def test_issue_comments_filtered_by_user_and_time() -> None:
    """Issue comments should filter by author and target day window."""
    cfg = GithubConfig(
        github_token="t",
        target_date=datetime(2024, 7, 1),
        include_types=[ChangeType.ISSUE_COMMENT],
        repo_filters=["o/r"],
        user="octo",
    )
    client = GithubClient(cfg)
    # Fake contributions to seed repo discovery
    data = {
        "data": {
            "user": {
                "contributionsCollection": {
                    "issueContributions": {"nodes": []},
                    "pullRequestContributions": {"nodes": []},
                    "pullRequestReviewContributions": {"nodes": []},
                    "commitContributionsByRepository": [
                        {"repository": {"nameWithOwner": "o/r"}}
                    ],
                }
            }
        }
    }
    responses.add(
        responses.POST,
        cfg.graphql_url,
        json=data,
        status=200,
    )
    # REST issue comments (one by octo in range, one by other user, one out of range)
    issues_url = f"{cfg.api_url}/repos/o/r/issues/comments"
    responses.add(
        responses.GET,
        issues_url,
        json=[
            {
                "id": 1,
                "created_at": "2024-07-01T12:00:00Z",
                "user": {"login": "octo"},
                "issue_url": "https://api.github.com/repos/o/r/issues/5",
                "html_url": "https://github.com/o/r/issues/5#comment-1",
            },
            {
                "id": 2,
                "created_at": "2024-07-01T12:00:00Z",
                "user": {"login": "someoneelse"},
                "issue_url": "https://api.github.com/repos/o/r/issues/6",
                "html_url": "https://github.com/o/r/issues/6#comment-2",
            },
            {
                "id": 3,
                "created_at": "2024-07-02T12:00:00Z",
                "user": {"login": "octo"},
                "issue_url": "https://api.github.com/repos/o/r/issues/7",
                "html_url": "https://github.com/o/r/issues/7#comment-3",
            },
        ],
        status=200,
    )

    changes = client.get_changes(
        datetime(2024, 7, 1, 0, 0, 0), datetime(2024, 7, 2, 0, 0, 0)
    )
    # Only one comment matches
    issue_comments = [c for c in changes if c.type is ChangeType.ISSUE_COMMENT]
    assert len(issue_comments) == 1
    assert issue_comments[0].title.startswith("Commented on issue #5")


@responses.activate
def test_pr_review_comments_filtered_by_user_and_time() -> None:
    """PR review comments should filter by author and target day window."""
    cfg = GithubConfig(
        github_token="t",
        target_date=datetime(2024, 7, 1),
        include_types=[ChangeType.PR_COMMENT],
        repo_filters=["o/r"],
        user="octo",
    )
    client = GithubClient(cfg)
    data = {
        "data": {
            "user": {
                "contributionsCollection": {
                    "issueContributions": {"nodes": []},
                    "pullRequestContributions": {"nodes": []},
                    "pullRequestReviewContributions": {"nodes": []},
                    "commitContributionsByRepository": [
                        {"repository": {"nameWithOwner": "o/r"}}
                    ],
                }
            }
        }
    }
    responses.add(responses.POST, cfg.graphql_url, json=data, status=200)
    # PR review comments
    prc_url = f"{cfg.api_url}/repos/o/r/pulls/comments"
    responses.add(
        responses.GET,
        prc_url,
        json=[
            {
                "id": 10,
                "created_at": "2024-07-01T01:00:00Z",
                "user": {"login": "octo"},
                "pull_request_url": "https://api.github.com/repos/o/r/pulls/42",
                "html_url": "https://github.com/o/r/pull/42#discussion_r10",
            },
            {
                "id": 11,
                "created_at": "2024-06-30T23:59:59Z",
                "user": {"login": "octo"},
                "pull_request_url": "https://api.github.com/repos/o/r/pulls/43",
                "html_url": "https://github.com/o/r/pull/43#discussion_r11",
            },
        ],
        status=200,
    )

    changes = client.get_changes(
        datetime(2024, 7, 1, 0, 0, 0), datetime(2024, 7, 2, 0, 0, 0)
    )
    pr_comments = [c for c in changes if c.type is ChangeType.PR_COMMENT]
    assert len(pr_comments) == 1
    assert pr_comments[0].title.startswith("Commented on PR #42")
