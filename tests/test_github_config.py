from datetime import datetime

from summarizer.github.config import GithubConfig
from summarizer.common.models import ChangeType


def test_from_env_defaults():
    cfg = GithubConfig.from_env(target_date=datetime(2024, 7, 1), env={})
    assert cfg.github_token is None
    assert cfg.api_url == "https://api.github.com"
    assert cfg.graphql_url == "https://api.github.com/graphql"
    assert cfg.is_active() is False
    # By default all ChangeTypes are included
    assert set(cfg.include_types) == set(ChangeType)


def test_from_env_parsing_include_and_filters():
    env = {
        "GITHUB_TOKEN": "t",
        "GITHUB_API_URL": "https://ghe.example.com/api/v3",
        "GITHUB_GRAPHQL_URL": "https://ghe.example.com/api/graphql",
        "GITHUB_USER": "octo",
        "GITHUB_ORGS": "one, two",
        "GITHUB_REPOS": "a/b, c/d",
        "GITHUB_INCLUDE": "commit,prs,issue_comment",  # 'prs' should be normalized by enum upper
        "GITHUB_SAFE_RATE": "true",
    }
    cfg = GithubConfig.from_env(target_date=datetime(2024, 7, 1), env=env)
    assert cfg.is_active() is True
    assert cfg.github_token == "t"
    assert cfg.api_url == "https://ghe.example.com/api/v3"
    assert cfg.graphql_url == "https://ghe.example.com/api/graphql"
    assert cfg.user == "octo"
    assert cfg.org_filters == ["one", "two"]
    assert cfg.repo_filters == ["a/b", "c/d"]
    assert cfg.safe_rate is True
    # include normalization: unsupported alias 'prs' should not break; ensure at least COMMIT present
    assert ChangeType.COMMIT in cfg.include_types


