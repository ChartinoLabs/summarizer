"""Comprehensive unit tests for the Webex Meetings module.

This test suite covers all functionality in summarizer.webex.meetings, including:
- Meeting model creation and validation
- Duration calculations
- State checking (scheduled vs cancelled)
- Multi-day meeting detection and splitting
- Business week calculations
- MeetingsClient API interactions with retry logic
- Date-based meeting filtering
- Timezone handling
"""

from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, Any, Generator
from zoneinfo import ZoneInfo

import pytest
import responses
from freezegun import freeze_time

from summarizer.webex.meetings import (
    Meeting,
    MeetingsClient,
    MeetingsListResponse,
    calculate_business_week_range,
    is_meeting_on_date,
)

if TYPE_CHECKING:
    from pathlib import Path

    from _pytest.logging import LogCaptureFixture
    from pytest_mock.plugin import MockerFixture


# Test Fixtures


@pytest.fixture
def sample_meeting_dict() -> dict[str, Any]:
    """Provide a basic meeting API response dictionary.

    Returns:
        Dictionary representing a typical API response for a single meeting.
    """
    return {
        "id": "meeting123",
        "meetingSeriesId": "series456",
        "title": "Daily Standup",
        "start": "2025-01-15T09:00:00-05:00",
        "end": "2025-01-15T09:30:00-05:00",
        "timezone": "America/New_York",
        "state": "scheduled",
        "meetingType": "scheduledMeeting",
        "isRecurring": False,
        "hostEmail": "host@example.com",
        "hostDisplayName": "John Host",
        "webLink": "https://webex.com/meet/meeting123",
        "sipAddress": "meeting123@webex.com",
        "meetingNumber": "123456789",
    }


@pytest.fixture
def sample_meeting(sample_meeting_dict: dict[str, Any]) -> Meeting:
    """Provide a Meeting model instance.

    Args:
        sample_meeting_dict: Dictionary fixture for meeting data.

    Returns:
        Meeting model initialized with sample data.
    """
    return Meeting(**sample_meeting_dict)


@pytest.fixture
def multi_day_meeting() -> Meeting:
    """Provide a meeting that spans three days.

    This meeting starts on Wednesday at 23:00 and ends on Friday at 02:00,
    crossing midnight boundaries twice.

    Returns:
        Meeting model spanning multiple days.
    """
    return Meeting(
        id="multi_day_123",
        title="Multi-Day Conference",
        start="2025-01-15T23:00:00-05:00",  # Wednesday 11 PM
        end="2025-01-17T02:00:00-05:00",  # Friday 2 AM
        timezone="America/New_York",
        state="scheduled",
        webLink="https://webex.com/meet/multi_day_123",
    )


@pytest.fixture
def cancelled_meeting() -> Meeting:
    """Provide a cancelled meeting.

    Returns:
        Meeting model with state='cancelled'.
    """
    return Meeting(
        id="cancelled_123",
        title="Cancelled Meeting",
        start="2025-01-15T10:00:00-05:00",
        end="2025-01-15T11:00:00-05:00",
        timezone="America/New_York",
        state="cancelled",
        webLink="https://webex.com/meet/cancelled_123",
    )


@pytest.fixture
def scheduled_meeting() -> Meeting:
    """Provide a scheduled meeting.

    Returns:
        Meeting model with state='scheduled'.
    """
    return Meeting(
        id="scheduled_123",
        title="Scheduled Meeting",
        start="2025-01-15T14:00:00-05:00",
        end="2025-01-15T15:00:00-05:00",
        timezone="America/New_York",
        state="scheduled",
        webLink="https://webex.com/meet/scheduled_123",
    )


@pytest.fixture
def meetings_client() -> Generator[MeetingsClient, None, None]:
    """Provide a MeetingsClient instance with mock token.

    Yields:
        MeetingsClient initialized with test token.
    """
    client = MeetingsClient(access_token="test_access_token_123")
    yield client
    client.close()


# Test Classes


class TestMeeting:
    """Test cases for Meeting model."""

    def test_meeting_creation(self, sample_meeting_dict: dict[str, Any]) -> None:
        """Basic Pydantic validation should accept valid meeting data.

        Args:
            sample_meeting_dict: Dictionary with valid meeting data.
        """
        meeting = Meeting(**sample_meeting_dict)

        assert meeting.id == "meeting123"
        assert meeting.title == "Daily Standup"
        assert meeting.state == "scheduled"
        assert meeting.timezone == "America/New_York"
        assert meeting.host_email == "host@example.com"

    def test_meeting_creation_with_minimal_fields(self) -> None:
        """Meeting should be created with only required fields.

        Tests that optional fields default correctly when not provided.
        """
        meeting = Meeting(
            id="minimal_123",
            title="Minimal Meeting",
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T11:00:00Z",
            timezone="UTC",
            webLink="https://webex.com/meet/minimal",
        )

        assert meeting.id == "minimal_123"
        assert meeting.state == "scheduled"  # Default value
        assert meeting.meeting_type == "meeting"  # Default value
        assert meeting.is_recurring is False  # Default value
        assert meeting.host_email is None

    def test_duration_minutes_property(self, sample_meeting: Meeting) -> None:
        """Verify duration calculation returns correct minutes.

        Args:
            sample_meeting: Meeting fixture with 30-minute duration.
        """
        duration = sample_meeting.duration_minutes

        assert duration == 30.0

    def test_duration_minutes_with_fractional_minutes(self) -> None:
        """Duration calculation should handle fractional minutes correctly.

        Tests a 45-minute meeting to verify decimal precision.
        """
        meeting = Meeting(
            id="test_123",
            title="45 Minute Meeting",
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T10:45:00Z",
            timezone="UTC",
            webLink="https://webex.com/meet/test",
        )

        assert meeting.duration_minutes == 45.0

    def test_duration_minutes_with_seconds(self) -> None:
        """Duration calculation should handle seconds correctly.

        Tests that duration includes fractional minutes from seconds.
        """
        meeting = Meeting(
            id="test_123",
            title="Meeting with Seconds",
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T10:30:30Z",  # 30 minutes 30 seconds
            timezone="UTC",
            webLink="https://webex.com/meet/test",
        )

        assert meeting.duration_minutes == 30.5

    def test_duration_minutes_invalid_format(self) -> None:
        """Invalid time format should raise ValueError.

        Tests error handling for malformed datetime strings.
        """
        meeting = Meeting(
            id="test_123",
            title="Invalid Times",
            start="invalid-datetime",
            end="also-invalid",
            timezone="UTC",
            webLink="https://webex.com/meet/test",
        )

        with pytest.raises(ValueError, match="Invalid meeting time format"):
            _ = meeting.duration_minutes

    def test_is_scheduled_property(self, scheduled_meeting: Meeting) -> None:
        """Verify state checking for scheduled meetings.

        Args:
            scheduled_meeting: Meeting with state='scheduled'.
        """
        assert scheduled_meeting.is_scheduled is True

    def test_is_scheduled_property_cancelled(self, cancelled_meeting: Meeting) -> None:
        """Cancelled meeting should not be considered scheduled.

        Args:
            cancelled_meeting: Meeting with state='cancelled'.
        """
        assert cancelled_meeting.is_scheduled is False

    def test_is_scheduled_property_other_states(self) -> None:
        """Non-scheduled states should return False.

        Tests various meeting states to ensure only 'scheduled' returns True.
        """
        states_to_test = ["active", "ended", "lobby", "inProgress", "cancelled"]

        for state in states_to_test:
            meeting = Meeting(
                id=f"meeting_{state}",
                title=f"Meeting in {state}",
                start="2025-01-15T10:00:00Z",
                end="2025-01-15T11:00:00Z",
                timezone="UTC",
                state=state,
                webLink="https://webex.com/meet/test",
            )
            assert meeting.is_scheduled is False, f"State '{state}' should not be scheduled"

    def test_spans_multiple_days_single_day(self, sample_meeting: Meeting) -> None:
        """Meeting within one day should return False.

        Args:
            sample_meeting: Meeting from 9:00-9:30 AM same day.
        """
        assert sample_meeting.spans_multiple_days() is False

    def test_spans_multiple_days_crosses_midnight(self) -> None:
        """Meeting crossing midnight boundary should return True.

        Tests a meeting that starts before midnight and ends after midnight.
        """
        meeting = Meeting(
            id="midnight_123",
            title="Midnight Meeting",
            start="2025-01-15T23:30:00-05:00",  # 11:30 PM
            end="2025-01-16T00:30:00-05:00",  # 12:30 AM next day
            timezone="America/New_York",
            webLink="https://webex.com/meet/midnight",
        )

        assert meeting.spans_multiple_days() is True

    def test_spans_multiple_days_exactly_at_midnight(self) -> None:
        """Meeting ending exactly at midnight should not span multiple days.

        Tests edge case where meeting ends at 23:59:59.
        """
        meeting = Meeting(
            id="edge_123",
            title="Edge Case Meeting",
            start="2025-01-15T22:00:00-05:00",
            end="2025-01-15T23:59:59-05:00",  # Just before midnight
            timezone="America/New_York",
            webLink="https://webex.com/meet/edge",
        )

        assert meeting.spans_multiple_days() is False

    def test_spans_multiple_days_starting_at_midnight(self) -> None:
        """Meeting starting at midnight should not span previous day.

        Tests edge case where meeting starts at 00:00:00.
        """
        meeting = Meeting(
            id="midnight_start_123",
            title="Midnight Start",
            start="2025-01-15T00:00:00-05:00",  # Exactly midnight
            end="2025-01-15T01:00:00-05:00",
            timezone="America/New_York",
            webLink="https://webex.com/meet/midnight_start",
        )

        assert meeting.spans_multiple_days() is False

    def test_split_by_day_single_day(self, sample_meeting: Meeting) -> None:
        """Single-day meeting should return list with one meeting.

        Args:
            sample_meeting: Meeting within single day.
        """
        segments = sample_meeting.split_by_day()

        assert len(segments) == 1
        assert segments[0].id == sample_meeting.id
        assert segments[0].start == sample_meeting.start
        assert segments[0].end == sample_meeting.end

    def test_split_by_day_two_days(self) -> None:
        """Meeting spanning two days should split correctly at midnight.

        Tests that a meeting crossing one midnight boundary splits into
        exactly two segments with correct time boundaries.
        """
        meeting = Meeting(
            id="two_day_123",
            title="Two Day Meeting",
            start="2025-01-15T22:00:00-05:00",  # 10 PM
            end="2025-01-16T02:00:00-05:00",  # 2 AM next day
            timezone="America/New_York",
            webLink="https://webex.com/meet/two_day",
        )

        segments = meeting.split_by_day()

        assert len(segments) == 2

        # First segment: 10 PM to 23:59:59.999999 same day
        assert segments[0].start == "2025-01-15T22:00:00-05:00"
        assert "2025-01-15T23:59:59" in segments[0].end

        # Second segment: 00:00:00 to 2 AM next day
        assert "2025-01-16T00:00:00" in segments[1].start
        assert segments[1].end == "2025-01-16T02:00:00-05:00"

    def test_split_by_day_three_days(self, multi_day_meeting: Meeting) -> None:
        """Meeting spanning three days should create three segments.

        Args:
            multi_day_meeting: Meeting from Wed 11 PM to Fri 2 AM.
        """
        segments = multi_day_meeting.split_by_day()

        assert len(segments) == 3

        # First segment: Wednesday 23:00 to 23:59:59
        assert "2025-01-15T23:00:00" in segments[0].start
        assert "2025-01-15T23:59:59" in segments[0].end

        # Second segment: Thursday 00:00 to 23:59:59
        assert "2025-01-16T00:00:00" in segments[1].start
        assert "2025-01-16T23:59:59" in segments[1].end

        # Third segment: Friday 00:00 to 02:00
        assert "2025-01-17T00:00:00" in segments[2].start
        assert "2025-01-17T02:00:00" in segments[2].end

    def test_split_by_day_with_timezone(self) -> None:
        """Split should handle timezone conversions correctly.

        Tests that splits occur at midnight in the meeting's local timezone,
        not UTC midnight.
        """
        # Meeting in Tokyo timezone (JST = UTC+9)
        meeting = Meeting(
            id="tokyo_123",
            title="Tokyo Meeting",
            start="2025-01-15T23:00:00+09:00",  # 11 PM JST
            end="2025-01-16T01:00:00+09:00",  # 1 AM JST next day
            timezone="Asia/Tokyo",
            webLink="https://webex.com/meet/tokyo",
        )

        segments = meeting.split_by_day()

        assert len(segments) == 2

        # Should split at midnight Tokyo time, not UTC midnight
        tokyo_tz = ZoneInfo("Asia/Tokyo")
        start_1 = datetime.fromisoformat(segments[0].start.replace("Z", "+00:00"))
        end_1 = datetime.fromisoformat(segments[0].end.replace("Z", "+00:00"))
        start_2 = datetime.fromisoformat(segments[1].start.replace("Z", "+00:00"))

        # Convert to Tokyo time and verify dates
        start_1_local = start_1.astimezone(tokyo_tz)
        end_1_local = end_1.astimezone(tokyo_tz)
        start_2_local = start_2.astimezone(tokyo_tz)

        assert start_1_local.date().day == 15
        assert end_1_local.date().day == 15
        assert start_2_local.date().day == 16

    @pytest.mark.parametrize(
        "timezone_str,start_time,end_time,expected_segments",
        [
            # Pacific time crossing midnight
            ("America/Los_Angeles", "2025-01-15T23:30:00-08:00", "2025-01-16T01:30:00-08:00", 2),
            # UTC crossing midnight
            ("UTC", "2025-01-15T23:00:00Z", "2025-01-16T02:00:00Z", 2),
            # Sydney time (UTC+11) crossing midnight
            ("Australia/Sydney", "2025-01-15T23:00:00+11:00", "2025-01-16T02:00:00+11:00", 2),
            # Single day meeting in various timezones
            ("America/New_York", "2025-01-15T10:00:00-05:00", "2025-01-15T11:00:00-05:00", 1),
            ("Europe/London", "2025-01-15T14:00:00Z", "2025-01-15T15:00:00Z", 1),
        ],
    )
    def test_split_by_day_multiple_timezones(
        self, timezone_str: str, start_time: str, end_time: str, expected_segments: int
    ) -> None:
        """Test split_by_day with various timezones.

        Args:
            timezone_str: IANA timezone identifier.
            start_time: Meeting start time in ISO format.
            end_time: Meeting end time in ISO format.
            expected_segments: Expected number of day segments.
        """
        meeting = Meeting(
            id="tz_test_123",
            title="Timezone Test",
            start=start_time,
            end=end_time,
            timezone=timezone_str,
            webLink="https://webex.com/meet/tz_test",
        )

        segments = meeting.split_by_day()

        assert len(segments) == expected_segments

    def test_split_by_day_preserves_meeting_properties(self, multi_day_meeting: Meeting) -> None:
        """Split segments should preserve all non-temporal meeting properties.

        Args:
            multi_day_meeting: Original meeting to split.
        """
        segments = multi_day_meeting.split_by_day()

        for segment in segments:
            assert segment.id == multi_day_meeting.id
            assert segment.title == multi_day_meeting.title
            assert segment.timezone == multi_day_meeting.timezone
            assert segment.state == multi_day_meeting.state
            assert segment.web_link == multi_day_meeting.web_link


class TestMeetingsClient:
    """Test cases for MeetingsClient API interaction."""

    def test_client_initialization(self) -> None:
        """Verify proper initialization with valid token.

        Tests that client initializes session with correct headers.
        """
        client = MeetingsClient(access_token="test_token")

        assert client.access_token == "test_token"
        assert client.session is not None
        assert client.session.headers["Authorization"] == "Bearer test_token"
        assert client.session.headers["Content-Type"] == "application/json"

        client.close()

    def test_client_initialization_empty_token(self) -> None:
        """Empty access token should raise ValueError.

        Tests validation of required access token parameter.
        """
        with pytest.raises(ValueError, match="Access token is required"):
            MeetingsClient(access_token="")

    def test_client_initialization_none_token(self) -> None:
        """None access token should raise ValueError.

        Tests validation when token is explicitly None.
        """
        with pytest.raises(ValueError, match="Access token is required"):
            MeetingsClient(access_token=None)  # type: ignore[arg-type]

    @responses.activate
    def test_make_request_success(self, meetings_client: MeetingsClient) -> None:
        """Mock successful API call should return expected response.

        Args:
            meetings_client: Client fixture for testing.
        """
        # Mock successful response
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            json={"items": []},
            status=200,
        )

        response = meetings_client._make_request("GET", "meetings")

        assert response.status_code == 200
        assert response.json() == {"items": []}

    @responses.activate
    def test_make_request_with_params(self, meetings_client: MeetingsClient) -> None:
        """Request should include query parameters correctly.

        Args:
            meetings_client: Client fixture for testing.
        """
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            json={"items": []},
            status=200,
        )

        response = meetings_client._make_request(
            "GET", "meetings", params={"max": 50, "from": "2025-01-01T00:00:00Z"}
        )

        assert response.status_code == 200
        # Verify params were included in request
        assert len(responses.calls) == 1
        assert "max=50" in responses.calls[0].request.url
        assert "from=2025-01-01" in responses.calls[0].request.url

    @responses.activate
    def test_make_request_retry_on_429(
        self, meetings_client: MeetingsClient, caplog: "LogCaptureFixture"
    ) -> None:
        """Verify retry logic with rate limiting (429 response).

        Args:
            meetings_client: Client fixture for testing.
            caplog: Pytest log capture fixture.
        """
        # First two calls return 429, third succeeds
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            status=429,
            headers={"Retry-After": "2"},
        )
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            status=429,
            headers={"Retry-After": "2"},
        )
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            json={"items": []},
            status=200,
        )

        response = meetings_client._make_request("GET", "meetings")

        assert response.status_code == 200
        assert len(responses.calls) == 3
        # Verify rate limit warning was logged
        assert "Rate limit hit (429)" in caplog.text

    @responses.activate
    def test_make_request_retry_on_network_error(
        self, meetings_client: MeetingsClient
    ) -> None:
        """Verify retry on RequestException (network errors).

        Args:
            meetings_client: Client fixture for testing.
        """
        import requests

        # First two calls fail with connection error, third succeeds
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            body=requests.exceptions.ConnectionError("Network error"),
        )
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            body=requests.exceptions.ConnectionError("Network error"),
        )
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            json={"items": []},
            status=200,
        )

        response = meetings_client._make_request("GET", "meetings")

        assert response.status_code == 200
        assert len(responses.calls) == 3

    @responses.activate
    def test_make_request_max_retries_exceeded(
        self, meetings_client: MeetingsClient
    ) -> None:
        """Verify failure after 3 retries (MAX_RETRIES).

        Args:
            meetings_client: Client fixture for testing.
        """
        # All attempts return 429
        for _ in range(5):  # More than MAX_RETRIES
            responses.add(
                responses.GET,
                "https://webexapis.com/v1/meetings",
                status=429,
                headers={"Retry-After": "1"},
            )

        with pytest.raises(Exception):  # Should raise after max retries
            meetings_client._make_request("GET", "meetings")

        # Should have made exactly MAX_RETRIES attempts
        assert len(responses.calls) == MeetingsClient.MAX_RETRIES

    @responses.activate
    def test_make_request_http_error_retries(
        self, meetings_client: MeetingsClient
    ) -> None:
        """HTTP errors trigger retries due to RequestException base class.

        Tests that HTTP errors (401, 403, etc.) retry because HTTPError
        inherits from RequestException and is caught by the retry decorator.

        Args:
            meetings_client: Client fixture for testing.
        """
        import requests

        # Add multiple 401 responses for retry attempts
        for _ in range(5):
            responses.add(
                responses.GET,
                "https://webexapis.com/v1/meetings",
                status=401,
                json={"message": "Unauthorized"},
            )

        with pytest.raises(requests.exceptions.HTTPError):
            meetings_client._make_request("GET", "meetings")

        # Should retry up to MAX_RETRIES
        assert len(responses.calls) == MeetingsClient.MAX_RETRIES

    @responses.activate
    def test_list_meetings_single_page(self, meetings_client: MeetingsClient) -> None:
        """Mock single page response without pagination.

        Args:
            meetings_client: Client fixture for testing.
        """
        mock_response = {
            "items": [
                {
                    "id": "meeting1",
                    "title": "Meeting 1",
                    "start": "2025-01-15T09:00:00Z",
                    "end": "2025-01-15T10:00:00Z",
                    "timezone": "UTC",
                    "webLink": "https://webex.com/meet/meeting1",
                }
            ]
        }

        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            json=mock_response,
            status=200,
        )

        meetings = list(meetings_client.list_meetings())

        assert len(meetings) == 1
        assert meetings[0].id == "meeting1"
        assert meetings[0].title == "Meeting 1"

    @responses.activate
    def test_list_meetings_pagination(self, meetings_client: MeetingsClient) -> None:
        """Mock multi-page response with Link headers for pagination.

        Args:
            meetings_client: Client fixture for testing.
        """
        # First page
        page1_response = {
            "items": [
                {
                    "id": "meeting1",
                    "title": "Meeting 1",
                    "start": "2025-01-15T09:00:00Z",
                    "end": "2025-01-15T10:00:00Z",
                    "timezone": "UTC",
                    "webLink": "https://webex.com/meet/meeting1",
                }
            ]
        }

        # Second page
        page2_response = {
            "items": [
                {
                    "id": "meeting2",
                    "title": "Meeting 2",
                    "start": "2025-01-15T11:00:00Z",
                    "end": "2025-01-15T12:00:00Z",
                    "timezone": "UTC",
                    "webLink": "https://webex.com/meet/meeting2",
                }
            ]
        }

        # First request with Link header
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            json=page1_response,
            status=200,
            headers={
                "Link": '<https://webexapis.com/v1/meetings?cursor=next123&max=100>; rel="next"'
            },
        )

        # Second request (no Link header = last page)
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            json=page2_response,
            status=200,
        )

        meetings = list(meetings_client.list_meetings())

        assert len(meetings) == 2
        assert meetings[0].id == "meeting1"
        assert meetings[1].id == "meeting2"
        assert len(responses.calls) == 2

    @responses.activate
    def test_list_meetings_with_date_filters(
        self, meetings_client: MeetingsClient
    ) -> None:
        """Verify query params for date filtering.

        Args:
            meetings_client: Client fixture for testing.
        """
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            json={"items": []},
            status=200,
        )

        from_date = datetime(2025, 1, 15, 0, 0, 0, tzinfo=UTC)
        to_date = datetime(2025, 1, 19, 23, 59, 59, tzinfo=UTC)

        list(meetings_client.list_meetings(from_date=from_date, to_date=to_date))

        assert len(responses.calls) == 1
        request_url = responses.calls[0].request.url
        assert "from=2025-01-15" in request_url
        assert "to=2025-01-19" in request_url

    @responses.activate
    def test_list_meetings_with_max_results(
        self, meetings_client: MeetingsClient
    ) -> None:
        """Verify max_results parameter is respected.

        Args:
            meetings_client: Client fixture for testing.
        """
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            json={"items": []},
            status=200,
        )

        list(meetings_client.list_meetings(max_results=50))

        assert len(responses.calls) == 1
        assert "max=50" in responses.calls[0].request.url

    @responses.activate
    def test_list_meetings_max_results_capped_at_100(
        self, meetings_client: MeetingsClient
    ) -> None:
        """Max results should be capped at 100 per API limits.

        Args:
            meetings_client: Client fixture for testing.
        """
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            json={"items": []},
            status=200,
        )

        list(meetings_client.list_meetings(max_results=200))

        assert len(responses.calls) == 1
        # Should be capped at 100
        assert "max=100" in responses.calls[0].request.url

    @responses.activate
    def test_get_business_week_meetings(
        self, meetings_client: MeetingsClient
    ) -> None:
        """Verify Mon-Fri calculation and scheduled filtering.

        Args:
            meetings_client: Client fixture for testing.
        """
        # Use explicit target date (Wednesday)
        target_date = datetime(2025, 1, 15, 10, 0, 0, tzinfo=UTC)

        # Mock meetings for the week
        mock_response = {
            "items": [
                {
                    "id": "scheduled1",
                    "title": "Scheduled Meeting",
                    "start": "2025-01-13T09:00:00Z",  # Monday
                    "end": "2025-01-13T10:00:00Z",
                    "timezone": "UTC",
                    "state": "scheduled",
                    "webLink": "https://webex.com/meet/scheduled1",
                },
                {
                    "id": "cancelled1",
                    "title": "Cancelled Meeting",
                    "start": "2025-01-14T09:00:00Z",  # Tuesday
                    "end": "2025-01-14T10:00:00Z",
                    "timezone": "UTC",
                    "state": "cancelled",
                    "webLink": "https://webex.com/meet/cancelled1",
                },
                {
                    "id": "ended1",
                    "title": "Ended Meeting",
                    "start": "2025-01-15T09:00:00Z",  # Wednesday
                    "end": "2025-01-15T10:00:00Z",
                    "timezone": "UTC",
                    "state": "ended",
                    "webLink": "https://webex.com/meet/ended1",
                },
                {
                    "id": "scheduled2",
                    "title": "Another Scheduled",
                    "start": "2025-01-17T09:00:00Z",  # Friday
                    "end": "2025-01-17T10:00:00Z",
                    "timezone": "UTC",
                    "state": "scheduled",
                    "webLink": "https://webex.com/meet/scheduled2",
                },
            ]
        }

        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            json=mock_response,
            status=200,
        )

        meetings = meetings_client.get_business_week_meetings(target_date=target_date)

        # Should only include scheduled meetings
        assert len(meetings) == 2
        assert all(m.state == "scheduled" for m in meetings)
        assert meetings[0].id == "scheduled1"
        assert meetings[1].id == "scheduled2"

        # Verify date range was Monday to Friday
        request_url = responses.calls[0].request.url
        assert "from=2025-01-13" in request_url  # Monday
        assert "to=2025-01-17" in request_url  # Friday

    @responses.activate
    @freeze_time("2025-01-16 14:00:00")  # Thursday
    def test_get_meetings_for_date(self, meetings_client: MeetingsClient) -> None:
        """Verify date-specific filtering.

        Args:
            meetings_client: Client fixture for testing.
        """
        target_date = datetime(2025, 1, 16, tzinfo=UTC)  # Thursday

        mock_response = {
            "items": [
                {
                    "id": "wed_meeting",
                    "title": "Wednesday Meeting",
                    "start": "2025-01-15T14:00:00Z",
                    "end": "2025-01-15T15:00:00Z",
                    "timezone": "UTC",
                    "state": "scheduled",
                    "webLink": "https://webex.com/meet/wed",
                },
                {
                    "id": "thu_meeting",
                    "title": "Thursday Meeting",
                    "start": "2025-01-16T10:00:00Z",
                    "end": "2025-01-16T11:00:00Z",
                    "timezone": "UTC",
                    "state": "scheduled",
                    "webLink": "https://webex.com/meet/thu",
                },
                {
                    "id": "fri_meeting",
                    "title": "Friday Meeting",
                    "start": "2025-01-17T10:00:00Z",
                    "end": "2025-01-17T11:00:00Z",
                    "timezone": "UTC",
                    "state": "scheduled",
                    "webLink": "https://webex.com/meet/fri",
                },
            ]
        }

        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            json=mock_response,
            status=200,
        )

        meetings = meetings_client.get_meetings_for_date(target_date)

        # Should only include Thursday meeting
        assert len(meetings) == 1
        assert meetings[0].id == "thu_meeting"

    @responses.activate
    @freeze_time("2025-01-16 14:00:00")
    def test_get_meetings_for_date_include_cancelled(
        self, meetings_client: MeetingsClient
    ) -> None:
        """Verify include_cancelled parameter works correctly.

        Args:
            meetings_client: Client fixture for testing.
        """
        target_date = datetime(2025, 1, 16, tzinfo=UTC)

        mock_response = {
            "items": [
                {
                    "id": "scheduled1",
                    "title": "Scheduled",
                    "start": "2025-01-16T10:00:00Z",
                    "end": "2025-01-16T11:00:00Z",
                    "timezone": "UTC",
                    "state": "scheduled",
                    "webLink": "https://webex.com/meet/scheduled1",
                },
                {
                    "id": "cancelled1",
                    "title": "Cancelled",
                    "start": "2025-01-16T14:00:00Z",
                    "end": "2025-01-16T15:00:00Z",
                    "timezone": "UTC",
                    "state": "cancelled",
                    "webLink": "https://webex.com/meet/cancelled1",
                },
            ]
        }

        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            json=mock_response,
            status=200,
        )

        # Test with include_cancelled=True
        meetings = meetings_client.get_meetings_for_date(
            target_date, include_cancelled=True
        )

        assert len(meetings) == 2

    @responses.activate
    def test_get_meetings_for_date_multi_day_meeting(
        self, meetings_client: MeetingsClient
    ) -> None:
        """Multi-day meetings should be included if they overlap target date.

        Args:
            meetings_client: Client fixture for testing.
        """
        target_date = datetime(2025, 1, 16, 12, 0, 0, tzinfo=UTC)  # Thursday noon

        mock_response = {
            "items": [
                {
                    "id": "multi_day",
                    "title": "Multi-Day Conference",
                    "start": "2025-01-15T22:00:00Z",  # Wednesday 10 PM
                    "end": "2025-01-17T02:00:00Z",  # Friday 2 AM
                    "timezone": "UTC",
                    "state": "scheduled",
                    "webLink": "https://webex.com/meet/multi",
                }
            ]
        }

        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetings",
            json=mock_response,
            status=200,
        )

        meetings = meetings_client.get_meetings_for_date(target_date)

        # Multi-day meeting overlaps Thursday, should be included
        assert len(meetings) == 1
        assert meetings[0].id == "multi_day"

    def test_close_session(self, meetings_client: MeetingsClient) -> None:
        """Verify session cleanup on close.

        Args:
            meetings_client: Client fixture for testing.
        """
        session = meetings_client.session

        meetings_client.close()

        # Session should be closed (internal state check)
        # Note: requests.Session doesn't expose a simple "is_closed" property
        # but calling close() should succeed without error
        assert session is not None


class TestBusinessWeekCalculations:
    """Test cases for business week calculation utilities."""

    @freeze_time("2025-01-13 10:00:00")  # Monday
    def test_calculate_business_week_range_monday(self) -> None:
        """Test from Monday should return same week.

        Tests that when given a Monday, the function returns that Monday
        through Friday.
        """
        target = datetime(2025, 1, 13, 10, 0, 0, tzinfo=UTC)  # Monday

        week_start, week_end = calculate_business_week_range(target)

        assert week_start.date() == datetime(2025, 1, 13).date()  # Monday
        assert week_start.hour == 0
        assert week_start.minute == 0

        assert week_end.date() == datetime(2025, 1, 17).date()  # Friday
        assert week_end.hour == 23
        assert week_end.minute == 59

    @freeze_time("2025-01-17 15:00:00")  # Friday
    def test_calculate_business_week_range_friday(self) -> None:
        """Test from Friday should return same week.

        Tests that when given a Friday, the function returns that week's
        Monday through Friday.
        """
        target = datetime(2025, 1, 17, 15, 0, 0, tzinfo=UTC)  # Friday

        week_start, week_end = calculate_business_week_range(target)

        assert week_start.date() == datetime(2025, 1, 13).date()  # Monday
        assert week_end.date() == datetime(2025, 1, 17).date()  # Friday

    @freeze_time("2025-01-18 10:00:00")  # Saturday
    def test_calculate_business_week_range_saturday(self) -> None:
        """Test from Saturday should return current week (Mon-Fri).

        Tests that when given a Saturday, the function returns the just-ended
        business week (Monday through Friday).
        """
        target = datetime(2025, 1, 18, 10, 0, 0, tzinfo=UTC)  # Saturday

        week_start, week_end = calculate_business_week_range(target)

        # Should return Monday-Friday of the week containing Saturday
        assert week_start.date() == datetime(2025, 1, 13).date()  # Monday
        assert week_end.date() == datetime(2025, 1, 17).date()  # Friday

    @freeze_time("2025-01-19 10:00:00")  # Sunday
    def test_calculate_business_week_range_sunday(self) -> None:
        """Test from Sunday should return current week (Mon-Fri).

        Tests that when given a Sunday, the function returns the just-ended
        business week (Monday through Friday).
        """
        target = datetime(2025, 1, 19, 10, 0, 0, tzinfo=UTC)  # Sunday

        week_start, week_end = calculate_business_week_range(target)

        assert week_start.date() == datetime(2025, 1, 13).date()  # Monday
        assert week_end.date() == datetime(2025, 1, 17).date()  # Friday

    @freeze_time("2025-01-15 12:30:45")  # Wednesday with specific time
    def test_calculate_business_week_range_preserves_timezone(self) -> None:
        """Week range should reset to midnight boundaries.

        Tests that the function returns start of Monday and end of Friday
        regardless of input time.
        """
        target = datetime(2025, 1, 15, 12, 30, 45, 123456, tzinfo=UTC)

        week_start, week_end = calculate_business_week_range(target)

        # Start should be Monday at 00:00:00.000000
        assert week_start.hour == 0
        assert week_start.minute == 0
        assert week_start.second == 0
        assert week_start.microsecond == 0

        # End should be Friday at 23:59:59.999999
        assert week_end.hour == 23
        assert week_end.minute == 59
        assert week_end.second == 59
        assert week_end.microsecond == 999999

    @pytest.mark.parametrize(
        "test_date,expected_monday,expected_friday",
        [
            # Various weeks throughout the year
            (datetime(2025, 1, 1, tzinfo=UTC), datetime(2024, 12, 30).date(), datetime(2025, 1, 3).date()),  # New Year (Wed)
            (datetime(2025, 2, 14, tzinfo=UTC), datetime(2025, 2, 10).date(), datetime(2025, 2, 14).date()),  # Valentine's (Fri)
            (datetime(2025, 7, 4, tzinfo=UTC), datetime(2025, 6, 30).date(), datetime(2025, 7, 4).date()),  # July 4th (Fri)
            (datetime(2025, 12, 25, tzinfo=UTC), datetime(2025, 12, 22).date(), datetime(2025, 12, 26).date()),  # Christmas (Thu)
        ],
    )
    def test_calculate_business_week_range_various_dates(
        self, test_date: datetime, expected_monday: datetime, expected_friday: datetime
    ) -> None:
        """Test business week calculation for various dates throughout the year.

        Args:
            test_date: Date to test.
            expected_monday: Expected Monday of business week.
            expected_friday: Expected Friday of business week.
        """
        week_start, week_end = calculate_business_week_range(test_date)

        assert week_start.date() == expected_monday
        assert week_end.date() == expected_friday


class TestIsMeetingOnDate:
    """Test cases for is_meeting_on_date utility function."""

    def test_meeting_on_target_date(self) -> None:
        """Meeting that starts and ends on target date should return True.

        Tests standard case where meeting is entirely within target date.
        """
        meeting = Meeting(
            id="test_123",
            title="Test Meeting",
            start="2025-01-15T10:00:00Z",
            end="2025-01-15T11:00:00Z",
            timezone="UTC",
            webLink="https://webex.com/meet/test",
        )

        target_date = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        assert is_meeting_on_date(meeting, target_date) is True

    def test_meeting_before_target_date(self) -> None:
        """Meeting entirely before target date should return False.

        Tests that meetings from previous days are excluded.
        """
        meeting = Meeting(
            id="test_123",
            title="Yesterday's Meeting",
            start="2025-01-14T10:00:00Z",
            end="2025-01-14T11:00:00Z",
            timezone="UTC",
            webLink="https://webex.com/meet/test",
        )

        target_date = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        assert is_meeting_on_date(meeting, target_date) is False

    def test_meeting_after_target_date(self) -> None:
        """Meeting entirely after target date should return False.

        Tests that meetings from future days are excluded.
        """
        meeting = Meeting(
            id="test_123",
            title="Tomorrow's Meeting",
            start="2025-01-16T10:00:00Z",
            end="2025-01-16T11:00:00Z",
            timezone="UTC",
            webLink="https://webex.com/meet/test",
        )

        target_date = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        assert is_meeting_on_date(meeting, target_date) is False

    def test_meeting_spanning_target_date(self) -> None:
        """Multi-day meeting overlapping target date should return True.

        Tests that meetings spanning multiple days are included when they
        overlap the target date.
        """
        meeting = Meeting(
            id="multi_day",
            title="Multi-Day Meeting",
            start="2025-01-14T22:00:00Z",  # Day before
            end="2025-01-16T02:00:00Z",  # Day after
            timezone="UTC",
            webLink="https://webex.com/meet/multi",
        )

        target_date = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        assert is_meeting_on_date(meeting, target_date) is True

    def test_meeting_ending_at_midnight(self) -> None:
        """Meeting ending exactly at midnight should be included in that day.

        Tests edge case where meeting ends at 23:59:59 of target date.
        """
        meeting = Meeting(
            id="edge_123",
            title="Late Meeting",
            start="2025-01-15T22:00:00Z",
            end="2025-01-15T23:59:59Z",
            timezone="UTC",
            webLink="https://webex.com/meet/edge",
        )

        target_date = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        assert is_meeting_on_date(meeting, target_date) is True

    def test_meeting_starting_at_midnight(self) -> None:
        """Meeting starting at midnight should be included in that day.

        Tests edge case where meeting starts at 00:00:00 of target date.
        """
        meeting = Meeting(
            id="early_123",
            title="Early Meeting",
            start="2025-01-15T00:00:00Z",
            end="2025-01-15T01:00:00Z",
            timezone="UTC",
            webLink="https://webex.com/meet/early",
        )

        target_date = datetime(2025, 1, 15, 12, 0, 0, tzinfo=UTC)

        assert is_meeting_on_date(meeting, target_date) is True

    def test_meeting_with_timezone_conversion(self) -> None:
        """Function should handle timezone conversions correctly.

        Tests that meetings in different timezones are correctly evaluated
        against target dates in other timezones.
        """
        # Meeting in Tokyo time (UTC+9)
        meeting = Meeting(
            id="tokyo_123",
            title="Tokyo Meeting",
            start="2025-01-16T09:00:00+09:00",  # 9 AM JST = midnight UTC Jan 16
            end="2025-01-16T10:00:00+09:00",
            timezone="Asia/Tokyo",
            webLink="https://webex.com/meet/tokyo",
        )

        # Target date in UTC
        target_date = datetime(2025, 1, 16, 1, 0, 0, tzinfo=UTC)

        # Meeting starts at Jan 16 midnight UTC, so it should match Jan 16 UTC
        assert is_meeting_on_date(meeting, target_date) is True

    @pytest.mark.parametrize(
        "meeting_start,meeting_end,target_date_str,expected",
        [
            # Meeting entirely on target date
            ("2025-01-15T10:00:00Z", "2025-01-15T11:00:00Z", "2025-01-15", True),
            # Meeting before target date
            ("2025-01-14T10:00:00Z", "2025-01-14T11:00:00Z", "2025-01-15", False),
            # Meeting after target date
            ("2025-01-16T10:00:00Z", "2025-01-16T11:00:00Z", "2025-01-15", False),
            # Meeting starts on target, ends next day
            ("2025-01-15T23:00:00Z", "2025-01-16T01:00:00Z", "2025-01-15", True),
            # Meeting starts previous day, ends on target
            ("2025-01-14T23:00:00Z", "2025-01-15T01:00:00Z", "2025-01-15", True),
        ],
    )
    def test_is_meeting_on_date_parametrized(
        self, meeting_start: str, meeting_end: str, target_date_str: str, expected: bool
    ) -> None:
        """Test is_meeting_on_date with various scenarios.

        Args:
            meeting_start: Meeting start time in ISO format.
            meeting_end: Meeting end time in ISO format.
            target_date_str: Target date string (YYYY-MM-DD).
            expected: Expected result (True/False).
        """
        meeting = Meeting(
            id="param_test",
            title="Parameterized Test",
            start=meeting_start,
            end=meeting_end,
            timezone="UTC",
            webLink="https://webex.com/meet/param",
        )

        target_date = datetime.fromisoformat(target_date_str).replace(tzinfo=UTC)

        assert is_meeting_on_date(meeting, target_date) is expected


class TestMeetingsListResponse:
    """Test cases for MeetingsListResponse model."""

    def test_empty_response(self) -> None:
        """Empty response should create model with empty items list.

        Tests default factory for items field.
        """
        response = MeetingsListResponse()

        assert response.items == []
        assert isinstance(response.items, list)

    def test_response_with_meetings(self, sample_meeting_dict: dict[str, Any]) -> None:
        """Response with meetings should parse correctly.

        Args:
            sample_meeting_dict: Sample meeting data.
        """
        response_data = {"items": [sample_meeting_dict]}

        response = MeetingsListResponse(**response_data)

        assert len(response.items) == 1
        assert isinstance(response.items[0], Meeting)
        assert response.items[0].id == "meeting123"

    def test_response_with_multiple_meetings(self) -> None:
        """Response with multiple meetings should parse all items.

        Tests that list parsing handles multiple meeting objects.
        """
        response_data = {
            "items": [
                {
                    "id": "meeting1",
                    "title": "Meeting 1",
                    "start": "2025-01-15T09:00:00Z",
                    "end": "2025-01-15T10:00:00Z",
                    "timezone": "UTC",
                    "webLink": "https://webex.com/meet/1",
                },
                {
                    "id": "meeting2",
                    "title": "Meeting 2",
                    "start": "2025-01-15T11:00:00Z",
                    "end": "2025-01-15T12:00:00Z",
                    "timezone": "UTC",
                    "webLink": "https://webex.com/meet/2",
                },
            ]
        }

        response = MeetingsListResponse(**response_data)

        assert len(response.items) == 2
        assert response.items[0].id == "meeting1"
        assert response.items[1].id == "meeting2"
