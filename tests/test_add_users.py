"""Tests for add_users_to_room functionality."""

from unittest.mock import MagicMock, Mock

import pytest
import requests
from webexpythonsdk.exceptions import ApiError
from webexpythonsdk.models.immutable import Room

from summarizer.webex import WebexClient, WebexConfig


def create_mock_api_error(status_code: int, message: str) -> ApiError:
    """Create a mock ApiError with the given status code and message.

    Args:
        status_code: HTTP status code (e.g., 404, 409, 403)
        message: Error message text

    Returns:
        ApiError instance that can be raised in tests
    """
    mock_request = Mock(spec=requests.Request)
    mock_request.method = "POST"
    mock_request.url = "https://api.ciscospark.com/v1/memberships"

    mock_response = Mock(spec=requests.Response)
    mock_response.status_code = status_code
    mock_response.reason = message
    mock_response.text = message
    mock_response.headers = {"Content-Type": "application/json"}
    mock_response.json.return_value = {"message": message}
    mock_response.request = mock_request

    return ApiError(mock_response)


class TestAddUsersToRoom:
    """Tests for WebexClient.add_users_to_room method."""

    @pytest.fixture
    def config(self) -> WebexConfig:
        """Create a test configuration."""
        from datetime import datetime

        return WebexConfig(
            webex_token="test_token",
            user_email="test@cisco.com",
            target_date=datetime(2024, 1, 1),
            context_window_minutes=15,
            passive_participation=False,
            time_display_format="12h",
            room_chunk_size=50,
            max_messages=1000,
            all_messages=False,
        )

    @pytest.fixture
    def mock_webex_api(self) -> MagicMock:
        """Create a mock WebexAPI client."""
        return MagicMock()

    @pytest.fixture
    def client(self, config: WebexConfig, mock_webex_api: MagicMock) -> WebexClient:
        """Create a WebexClient with mocked API."""
        return WebexClient(config, client=mock_webex_api)

    def test_add_users_success(
        self, client: WebexClient, mock_webex_api: MagicMock
    ) -> None:
        """Test successfully adding users to a room."""
        # Mock room retrieval
        mock_room = MagicMock(spec=Room)
        mock_room.title = "Test Room"
        mock_room.id = "room123"
        mock_webex_api.rooms.get.return_value = mock_room

        # Mock membership creation
        mock_webex_api.memberships.create.return_value = MagicMock()

        emails = ["user1@cisco.com", "user2@cisco.com", "user3@cisco.com"]
        successful, failed = client.add_users_to_room("room123", emails)

        assert len(successful) == 3
        assert len(failed) == 0
        assert successful == emails
        assert mock_webex_api.memberships.create.call_count == 3

    def test_add_users_already_member(
        self, client: WebexClient, mock_webex_api: MagicMock
    ) -> None:
        """Test that users already in room are counted as successful."""
        # Mock room retrieval
        mock_room = MagicMock(spec=Room)
        mock_room.title = "Test Room"
        mock_room.id = "room123"
        mock_webex_api.rooms.get.return_value = mock_room

        # Mock membership creation - simulate 409 conflict (already member)
        mock_webex_api.memberships.create.side_effect = create_mock_api_error(
            409, "Conflict: User already a member"
        )

        emails = ["user1@cisco.com"]
        successful, failed = client.add_users_to_room("room123", emails)

        assert len(successful) == 1
        assert len(failed) == 0
        assert successful[0] == "user1@cisco.com"

    def test_add_users_room_not_found(
        self, client: WebexClient, mock_webex_api: MagicMock
    ) -> None:
        """Test that ApiError is raised when room is not found."""
        # Mock room retrieval to raise 404
        mock_webex_api.rooms.get.side_effect = create_mock_api_error(404, "Not Found")

        emails = ["user1@cisco.com"]

        with pytest.raises(ApiError):
            client.add_users_to_room("nonexistent_room", emails)

    def test_add_users_mixed_results(
        self, client: WebexClient, mock_webex_api: MagicMock
    ) -> None:
        """Test adding users with both successes and failures."""
        # Mock room retrieval
        mock_room = MagicMock(spec=Room)
        mock_room.title = "Test Room"
        mock_room.id = "room123"
        mock_webex_api.rooms.get.return_value = mock_room

        # Mock membership creation with mixed results
        def create_side_effect(*args: str, **kwargs: str) -> MagicMock:
            email = kwargs.get("personEmail", "")
            if email == "user2@cisco.com":
                raise create_mock_api_error(403, "Forbidden: Invalid user")
            return MagicMock()

        mock_webex_api.memberships.create.side_effect = create_side_effect

        emails = ["user1@cisco.com", "user2@cisco.com", "user3@cisco.com"]
        successful, failed = client.add_users_to_room("room123", emails)

        assert len(successful) == 2
        assert len(failed) == 1
        assert "user1@cisco.com" in successful
        assert "user3@cisco.com" in successful
        assert failed[0][0] == "user2@cisco.com"
        assert "Forbidden" in failed[0][1]

    def test_add_users_unexpected_error(
        self, client: WebexClient, mock_webex_api: MagicMock
    ) -> None:
        """Test handling of unexpected non-API errors."""
        # Mock room retrieval
        mock_room = MagicMock(spec=Room)
        mock_room.title = "Test Room"
        mock_room.id = "room123"
        mock_webex_api.rooms.get.return_value = mock_room

        # Mock membership creation with unexpected error
        mock_webex_api.memberships.create.side_effect = ValueError("Unexpected error")

        emails = ["user1@cisco.com"]
        successful, failed = client.add_users_to_room("room123", emails)

        assert len(successful) == 0
        assert len(failed) == 1
        assert failed[0][0] == "user1@cisco.com"
        assert "Unexpected error" in failed[0][1]

    def test_add_users_empty_list(
        self, client: WebexClient, mock_webex_api: MagicMock
    ) -> None:
        """Test adding an empty list of users."""
        # Mock room retrieval
        mock_room = MagicMock(spec=Room)
        mock_room.title = "Test Room"
        mock_room.id = "room123"
        mock_webex_api.rooms.get.return_value = mock_room

        emails: list[str] = []
        successful, failed = client.add_users_to_room("room123", emails)

        assert len(successful) == 0
        assert len(failed) == 0
        assert mock_webex_api.memberships.create.call_count == 0

    def test_add_users_duplicate_emails(
        self, client: WebexClient, mock_webex_api: MagicMock
    ) -> None:
        """Test adding users with duplicate emails in the list."""
        # Mock room retrieval
        mock_room = MagicMock(spec=Room)
        mock_room.title = "Test Room"
        mock_room.id = "room123"
        mock_webex_api.rooms.get.return_value = mock_room

        # Mock membership creation
        mock_webex_api.memberships.create.return_value = MagicMock()

        # List contains duplicates
        emails = ["user1@cisco.com", "user2@cisco.com", "user1@cisco.com"]
        successful, failed = client.add_users_to_room("room123", emails)

        # All should be attempted (deduplication is not this method's responsibility)
        assert len(successful) == 3
        assert mock_webex_api.memberships.create.call_count == 3
