"""Unit tests for GithubClient GraphQL viewer identity."""

from datetime import datetime

import responses

from summarizer.github.client import GithubClient
from summarizer.github.config import GithubConfig


@responses.activate
def test_get_viewer_success() -> None:
    """Viewer login should be resolved when token is valid."""
    cfg = GithubConfig(github_token="t", target_date=datetime(2024, 7, 1))
    client = GithubClient(cfg)
    responses.add(
        responses.POST,
        cfg.graphql_url,
        json={"data": {"viewer": {"login": "octocat"}}},
        status=200,
    )
    ident = client.get_viewer()
    assert ident.login == "octocat"


@responses.activate
def test_get_viewer_unauthorized() -> None:
    """Unauthorized responses should raise a ValueError."""
    cfg = GithubConfig(github_token="bad", target_date=datetime(2024, 7, 1))
    client = GithubClient(cfg)
    responses.add(responses.POST, cfg.graphql_url, json={}, status=401)
    try:
        client.get_viewer()
    except ValueError as exc:
        assert "Unauthorized" in str(exc)
    else:
        raise AssertionError("expected error")


@responses.activate
def test_get_viewer_graphql_errors() -> None:
    """GraphQL errors in a 200 response should raise a ValueError."""
    cfg = GithubConfig(github_token="t", target_date=datetime(2024, 7, 1))
    client = GithubClient(cfg)
    responses.add(
        responses.POST,
        cfg.graphql_url,
        json={"errors": [{"message": "Something bad"}]},
        status=200,
    )
    try:
        client.get_viewer()
    except ValueError as exc:
        assert "Something bad" in str(exc)
    else:
        raise AssertionError("expected error")
