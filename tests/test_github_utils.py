"""Tests for the GitHub utilities."""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from github import Github

from webex_summarizer.config import AppConfig
from webex_summarizer.github_utils import GitHubClient


class TestGitHubClient(unittest.TestCase):
    """Test cases for the GitHub client."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = AppConfig(
            webex_token="fake_token",
            github_token="fake_token",
            github_base_url="https://github.com/api/v3",
            user_email="test@example.com",
            target_date=datetime(2023, 1, 1),
            organizations_to_ignore=["org1", "org2"]
        )
        self.mock_github = MagicMock(spec=Github)
        self.client = GitHubClient(self.config, self.mock_github)

    @patch('webex_summarizer.github_utils.get_github_commits')
    def test_get_commits(self, mock_get_commits):
        """Test get_commits method."""
        # Arrange
        mock_get_commits.return_value = [
            {
                "time": datetime(2023, 1, 1, 12, 0, tzinfo=timezone.utc),
                "repo": "test-repo",
                "message": "Test commit",
                "sha": "abc1234"
            }
        ]
        
        # Act
        result = self.client.get_commits(self.config.target_date, timezone.utc)
        
        # Assert
        mock_get_commits.assert_called_once_with(
            self.mock_github, 
            self.config.target_date, 
            timezone.utc, 
            self.config.organizations_to_ignore
        )
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["repo"], "test-repo")
        self.assertEqual(result[0]["message"], "Test commit")
