"""Tests for the Webex module."""

import unittest
from datetime import UTC, datetime
from unittest.mock import MagicMock

from webexpythonsdk import WebexAPI

from webex_summarizer.config import AppConfig
from webex_summarizer.webex import WebexClient


class TestWebexClient(unittest.TestCase):
    """Test cases for the Webex client."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.config = AppConfig(
            webex_token="fake_token",
            user_email="test@example.com",
            target_date=datetime(2023, 1, 1),
            room_chunk_size=2,  # Small chunk for test
        )
        self.mock_webex = MagicMock(spec=WebexAPI)
        # Mock the people endpoint
        self.mock_webex.people = MagicMock()
        self.mock_webex.people.me.return_value = MagicMock(
            id="user123", displayName="Test User"
        )
        self.mock_webex.rooms = MagicMock()

        self.client = WebexClient(self.config, self.mock_webex)

    def test_get_me(self) -> None:
        """Test get_me method."""
        # Act
        result = self.client.get_me()

        # Assert
        self.assertEqual(result.display_name, "Test User")
        # Verify caching works - should call the API only once
        self.client.get_me()
        self.mock_webex.people.me.assert_called_once()

    def test_get_activity(self) -> None:
        """Test get_activity method."""
        # Arrange
        mock_room1 = MagicMock(
            id="room1",
            title="Room 1",
            lastActivity=datetime(2023, 1, 1, 12, 0),
            type="direct",
        )
        mock_room2 = MagicMock(
            id="room2",
            title="Room 2",
            lastActivity=datetime(2023, 1, 1, 13, 0),
            type="group",
        )
        self.mock_webex.rooms.list.return_value = [mock_room1, mock_room2]

        # Patch get_messages to return MessageAnalysisResult for each room
        from datetime import tzinfo

        from webexpythonsdk.models.immutable import Room

        from webex_summarizer.webex import (
            Message,
            MessageAnalysisResult,
            SpaceType,
            User,
        )

        def fake_get_messages(
            client: WebexAPI,
            date: datetime,
            user_email: str,
            room: Room,
            local_tz: tzinfo,
        ) -> MessageAnalysisResult:
            sender = User(id="user123", display_name="Test User")
            msg = Message(
                id="msg1" if room.id == "room1" else "msg2",
                space_id=room.id,
                space_type=SpaceType.DM if room.id == "room1" else SpaceType.GROUP,
                space_name=room.title,
                sender=sender,
                recipients=[],
                timestamp=datetime(2023, 1, 1, 10 if room.id == "room1" else 11, 0),
                content=f"Message {1 if room.id == 'room1' else 2}",
            )
            return MessageAnalysisResult(
                room=room,
                messages=[msg],
                last_activity=msg.timestamp,
                had_activity_on_or_after_date=True,
            )

        import webex_summarizer.webex as webex_mod

        orig_get_messages = webex_mod.get_messages
        webex_mod.get_messages = fake_get_messages

        # Act
        result = self.client.get_activity(self.config.target_date, UTC)

        # Assert
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0].content, "Message 1")
        self.assertEqual(result[1].content, "Message 2")

        # Clean up
        webex_mod.get_messages = orig_get_messages
