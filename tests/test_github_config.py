"""Tests for GithubConfig construction and defaults."""

from datetime import datetime

from summarizer.common.models import ChangeType
from summarizer.github.config import GithubConfig


def test_defaults_with_minimal_input() -> None:
    """Defaults should be sensible when minimal arguments are provided."""
    cfg = GithubConfig(
        github_token=None,
        target_date=datetime(2024, 7, 1),
    )
    assert cfg.github_token is None
    assert cfg.api_url == "https://api.github.com"
    assert cfg.graphql_url == "https://api.github.com/graphql"
    assert cfg.is_active() is False
    # By default all ChangeTypes are included
    assert set(cfg.include_types) == set(ChangeType)


def test_explicit_args_and_filters() -> None:
    """Explicit arguments should populate fields; include_types passed directly."""
    cfg = GithubConfig(
        github_token="t",
        target_date=datetime(2024, 7, 1),
        api_url="https://ghe.example.com/api/v3",
        graphql_url="https://ghe.example.com/api/graphql",
        user="octo",
        org_filters=["one", "two"],
        repo_filters=["a/b", "c/d"],
        include_types=[ChangeType.COMMIT, ChangeType.PULL_REQUEST],
        safe_rate=True,
    )
    assert cfg.is_active() is True
    assert cfg.github_token == "t"
    assert cfg.api_url == "https://ghe.example.com/api/v3"
    assert cfg.graphql_url == "https://ghe.example.com/api/graphql"
    assert cfg.user == "octo"
    assert cfg.org_filters == ["one", "two"]
    assert cfg.repo_filters == ["a/b", "c/d"]
    assert cfg.safe_rate is True
    assert cfg.include_types == {ChangeType.COMMIT, ChangeType.PULL_REQUEST}
