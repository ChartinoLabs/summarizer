"""Tests for the Webex module."""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from webexpythonsdk import WebexAPI

from webex_summarizer.config import AppConfig
from webex_summarizer.webex import WebexClient


class TestWebexClient(unittest.TestCase):
    """Test cases for the Webex client."""

    def setUp(self):
        """Set up test fixtures."""
        self.config = AppConfig(
            webex_token="fake_token",
            github_token="fake_token",
            github_base_url="https://api.github.com",
            user_email="test@example.com",
            target_date=datetime(2023, 1, 1),
        )
        self.mock_webex = MagicMock(spec=WebexAPI)
        # Mock the people endpoint
        self.mock_webex.people = MagicMock()
        self.mock_webex.people.me.return_value = MagicMock(displayName="Test User")
        
        self.client = WebexClient(self.config, self.mock_webex)

    def test_get_me(self):
        """Test get_me method."""
        # Act
        result = self.client.get_me()
        
        # Assert
        self.assertEqual(result.displayName, "Test User")
        # Verify caching works - should call the API only once
        self.client.get_me()
        self.mock_webex.people.me.assert_called_once()

    @patch('webex_summarizer.webex.get_rooms_with_activity')
    @patch('webex_summarizer.webex.get_messages')
    def test_get_activity(self, mock_get_messages, mock_get_rooms):
        """Test get_activity method."""
        # Arrange
        mock_room1 = MagicMock(id="room1", title="Room 1")
        mock_room2 = MagicMock(id="room2", title="Room 2")
        mock_get_rooms.return_value = [mock_room1, mock_room2]
        
        mock_get_messages.side_effect = [
            [{"time": datetime(2023, 1, 1, 10, 0), "space": "Room 1", "text": "Message 1"}],
            [{"time": datetime(2023, 1, 1, 11, 0), "space": "Room 2", "text": "Message 2"}]
        ]
        
        # Act
        result = self.client.get_activity(self.config.target_date, timezone.utc)
        
        # Assert
        self.assertEqual(len(result), 2)
        # Check if results are sorted by time
        self.assertEqual(result[0]["text"], "Message 1")
        self.assertEqual(result[1]["text"], "Message 2")
        mock_get_rooms.assert_called_once_with(self.mock_webex, self.config.target_date, timezone.utc)
        self.assertEqual(mock_get_messages.call_count, 2)
