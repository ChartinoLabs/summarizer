"""Tests for Webex meeting transcript and summary features."""

import unittest
from datetime import UTC, datetime
from io import StringIO
from unittest.mock import MagicMock, patch

import responses
from rich.console import Console
from webexpythonsdk import WebexAPI

from summarizer.common.console_ui import (
    display_meetings,
    display_meetings_summary,
)
from summarizer.common.models import (
    Meeting,
    MeetingSummary,
    TranscriptSnippet,
    User,
)
from summarizer.webex.client import WebexClient
from summarizer.webex.config import WebexConfig


def _make_config(**overrides: object) -> WebexConfig:
    """Build a WebexConfig with sensible defaults for tests."""
    defaults = dict(
        webex_token="fake_token",
        user_email="test@example.com",
        target_date=datetime(2024, 6, 1),
        room_chunk_size=2,
        include_meetings=True,
    )
    defaults.update(overrides)
    return WebexConfig(**defaults)


def _make_meeting(**overrides: object) -> Meeting:
    """Build a Meeting with sensible defaults for tests."""
    defaults = dict(
        id="meeting-1",
        title="Daily Standup",
        start_time=datetime(2024, 6, 1, 9, 0, tzinfo=UTC),
        end_time=datetime(2024, 6, 1, 9, 30, tzinfo=UTC),
        duration_seconds=1800,
        host=User(id="host-1", display_name="Host User"),
    )
    defaults.update(overrides)
    return Meeting(**defaults)


# =============================================================================
# Client tests
# =============================================================================


class TestWebexApiGet(unittest.TestCase):
    """Tests for the _webex_api_get REST helper."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.config = _make_config()
        self.mock_webex = MagicMock(spec=WebexAPI)
        self.mock_webex.people = MagicMock()
        self.mock_webex.people.me.return_value = MagicMock(id="u1", displayName="Test")
        self.client = WebexClient(self.config, self.mock_webex)

    @responses.activate
    def test_successful_get(self) -> None:
        """Should return parsed JSON on 200."""
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/test",
            json={"items": [1, 2]},
            status=200,
        )
        result = self.client._webex_api_get("/test")
        assert result == {"items": [1, 2]}

    @responses.activate
    def test_404_returns_none(self) -> None:
        """Should return None on 404."""
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/test",
            json={"message": "not found"},
            status=404,
        )
        result = self.client._webex_api_get("/test")
        assert result is None

    @responses.activate
    def test_403_returns_none(self) -> None:
        """Should return None on 403 (missing scope)."""
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/test",
            json={"message": "forbidden"},
            status=403,
        )
        result = self.client._webex_api_get("/test")
        assert result is None

    @responses.activate
    def test_500_returns_none(self) -> None:
        """Should return None on server error."""
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/test",
            json={"message": "error"},
            status=500,
        )
        result = self.client._webex_api_get("/test")
        assert result is None


class TestGetMeetingsForDate(unittest.TestCase):
    """Tests for get_meetings_for_date via SDK meetings.list()."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.config = _make_config()
        self.mock_webex = MagicMock(spec=WebexAPI)
        self.mock_webex.people = MagicMock()
        self.mock_webex.people.me.return_value = MagicMock(id="u1", displayName="Test")
        self.mock_webex.meetings = MagicMock()
        self.client = WebexClient(self.config, self.mock_webex)

    def test_returns_meetings(self) -> None:
        """Should parse SDK meeting objects into Meeting dataclasses."""
        sdk_meeting = MagicMock()
        sdk_meeting.id = "m1"
        sdk_meeting.title = "Standup"
        sdk_meeting.start = "2024-06-01T09:00:00+00:00"
        sdk_meeting.end = "2024-06-01T09:30:00+00:00"
        sdk_meeting.hostUserId = "host1"
        sdk_meeting.hostDisplayName = "Host"
        sdk_meeting.meetingSeriesId = "series1"
        sdk_meeting.siteUrl = "example.webex.com"

        self.mock_webex.meetings.list.return_value = [sdk_meeting]

        result = self.client.get_meetings_for_date(datetime(2024, 6, 1), UTC)
        assert len(result) == 1
        assert result[0].id == "m1"
        assert result[0].title == "Standup"
        assert result[0].duration_seconds == 1800
        assert result[0].host.display_name == "Host"

    def test_empty_on_api_error(self) -> None:
        """Should return empty list on API error."""
        import requests as req
        from webexpythonsdk.exceptions import ApiError

        resp = req.Response()
        resp.status_code = 500
        resp._content = b"error"
        self.mock_webex.meetings.list.side_effect = ApiError(resp)

        result = self.client.get_meetings_for_date(datetime(2024, 6, 1), UTC)
        assert result == []


class TestGetTranscriptsForDate(unittest.TestCase):
    """Tests for get_meeting_transcripts_for_date via REST."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.config = _make_config()
        self.mock_webex = MagicMock(spec=WebexAPI)
        self.mock_webex.people = MagicMock()
        self.mock_webex.people.me.return_value = MagicMock(id="u1", displayName="Test")
        self.client = WebexClient(self.config, self.mock_webex)

    @responses.activate
    def test_returns_transcript_mapping(self) -> None:
        """Should return {meetingId: transcriptId} mapping."""
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetingTranscripts",
            json={
                "items": [
                    {"meetingId": "m1", "id": "t1"},
                    {"meetingId": "m2", "id": "t2"},
                ]
            },
            status=200,
        )
        result = self.client.get_meeting_transcripts_for_date(datetime(2024, 6, 1), UTC)
        assert result == {"m1": "t1", "m2": "t2"}

    @responses.activate
    def test_empty_on_404(self) -> None:
        """Should return empty dict on 404."""
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetingTranscripts",
            json={"message": "not found"},
            status=404,
        )
        result = self.client.get_meeting_transcripts_for_date(datetime(2024, 6, 1), UTC)
        assert result == {}


class TestGetTranscriptSnippets(unittest.TestCase):
    """Tests for get_transcript_snippets via REST."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.config = _make_config()
        self.mock_webex = MagicMock(spec=WebexAPI)
        self.mock_webex.people = MagicMock()
        self.mock_webex.people.me.return_value = MagicMock(id="u1", displayName="Test")
        self.client = WebexClient(self.config, self.mock_webex)

    @responses.activate
    def test_returns_snippets(self) -> None:
        """Should parse transcript snippets into TranscriptSnippet dataclasses."""
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetingTranscripts/t1/snippets",
            json={
                "items": [
                    {
                        "personId": "p1",
                        "personName": "Alice",
                        "text": "Hello everyone",
                        "startTime": "2024-06-01T09:01:00+00:00",
                    },
                    {
                        "personId": "p2",
                        "personName": "Bob",
                        "text": "Hi Alice",
                    },
                ]
            },
            status=200,
        )
        result = self.client.get_transcript_snippets("t1")
        assert len(result) == 2
        assert result[0].speaker.display_name == "Alice"
        assert result[0].text == "Hello everyone"
        assert result[0].start_time is not None
        assert result[1].speaker.display_name == "Bob"
        assert result[1].start_time is None

    @responses.activate
    def test_returns_all_snippets_without_cap(self) -> None:
        """Should return all snippets without a cap."""
        items = [
            {"personId": f"p{i}", "personName": f"Speaker {i}", "text": f"Line {i}"}
            for i in range(20)
        ]
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetingTranscripts/t1/snippets",
            json={"items": items},
            status=200,
        )
        result = self.client.get_transcript_snippets("t1")
        assert len(result) == 20


class TestGetMeetingSummary(unittest.TestCase):
    """Tests for get_meeting_summary via REST."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.config = _make_config()
        self.mock_webex = MagicMock(spec=WebexAPI)
        self.mock_webex.people = MagicMock()
        self.mock_webex.people.me.return_value = MagicMock(id="u1", displayName="Test")
        self.client = WebexClient(self.config, self.mock_webex)

    @responses.activate
    def test_returns_summary(self) -> None:
        """Should parse meeting summary into MeetingSummary dataclass."""
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetingSummaries",
            json={
                "items": [
                    {
                        "overview": "Team discussed Q2 goals",
                        "notes": ["Note 1", "Note 2"],
                        "actionItems": ["Action 1"],
                    }
                ]
            },
            status=200,
        )
        result = self.client.get_meeting_summary("m1")
        assert result is not None
        assert result.overview == "Team discussed Q2 goals"
        assert len(result.notes) == 2
        assert len(result.action_items) == 1

    @responses.activate
    def test_none_on_404(self) -> None:
        """Should return None when no summary available."""
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetingSummaries",
            json={"message": "not found"},
            status=404,
        )
        result = self.client.get_meeting_summary("m1")
        assert result is None

    @responses.activate
    def test_none_on_empty_items(self) -> None:
        """Should return None when items list is empty."""
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetingSummaries",
            json={"items": []},
            status=200,
        )
        result = self.client.get_meeting_summary("m1")
        assert result is None


# =============================================================================
# Display tests
# =============================================================================


class TestDisplayMeetings(unittest.TestCase):
    """Tests for display_meetings output."""

    def test_empty_meetings(self) -> None:
        """Should display 'no meetings' message for empty list."""
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True, width=120)
        with patch("summarizer.common.console_ui.console", test_console):
            display_meetings([])
        output = buf.getvalue()
        assert "No meetings found" in output

    def test_meeting_with_summary_and_transcript(self) -> None:
        """Should display meeting metadata, summary, and transcript."""
        meeting = _make_meeting(
            summary=MeetingSummary(
                overview="Discussed roadmap",
                notes=["Note A"],
                action_items=["Action B"],
            ),
            transcript_snippets=[
                TranscriptSnippet(
                    speaker=User(id="s1", display_name="Alice"),
                    text="Hello world",
                ),
            ],
        )
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True, width=120)
        with patch("summarizer.common.console_ui.console", test_console):
            display_meetings([meeting])
        output = buf.getvalue()
        assert "Daily Standup" in output
        assert "Host User" in output
        assert "Discussed roadmap" in output
        assert "Note A" in output
        assert "Action B" in output
        assert "Alice" in output
        assert "Hello world" in output

    def test_meeting_without_extras(self) -> None:
        """Should display meeting metadata only when no summary/transcript."""
        meeting = _make_meeting()
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True, width=120)
        with patch("summarizer.common.console_ui.console", test_console):
            display_meetings([meeting])
        output = buf.getvalue()
        assert "Daily Standup" in output
        assert "AI Summary" not in output
        assert "Transcript" not in output


class TestDisplayMeetingsSummary(unittest.TestCase):
    """Tests for display_meetings_summary output."""

    def test_empty_meetings(self) -> None:
        """Should produce no output for empty list."""
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True, width=120)
        with patch("summarizer.common.console_ui.console", test_console):
            display_meetings_summary([])
        output = buf.getvalue()
        assert output.strip() == ""

    def test_summary_table(self) -> None:
        """Should render a summary table with Yes/No indicators."""
        meetings = [
            _make_meeting(
                summary=MeetingSummary(overview="Overview"),
                transcript_snippets=[
                    TranscriptSnippet(
                        speaker=User(id="s1", display_name="A"),
                        text="Text",
                    )
                ],
            ),
            _make_meeting(id="meeting-2", title="Sprint Retro"),
        ]
        buf = StringIO()
        test_console = Console(file=buf, force_terminal=True, width=120)
        with patch("summarizer.common.console_ui.console", test_console):
            display_meetings_summary(meetings)
        output = buf.getvalue()
        assert "Meeting Overview" in output
        assert "Daily Standup" in output
        assert "Sprint Retro" in output
        assert "Total meetings" in output


# =============================================================================
# Runner integration tests
# =============================================================================


class TestRunnerMeetingIntegration(unittest.TestCase):
    """Tests for meeting integration in WebexRunner."""

    def setUp(self) -> None:
        """Set up test fixtures."""
        self.config = _make_config(include_meetings=True)
        self.mock_webex = MagicMock(spec=WebexAPI)
        self.mock_webex.people = MagicMock()
        self.mock_webex.people.me.return_value = MagicMock(
            id="u1", displayName="Test User"
        )
        self.mock_webex.rooms = MagicMock()
        self.mock_webex.rooms.list.return_value = []
        self.mock_webex.meetings = MagicMock()
        self.mock_webex.meetings.list.return_value = []

    @responses.activate
    def test_meetings_fetched_when_enabled(self) -> None:
        """Runner should call get_meetings_with_details when meetings enabled."""
        from summarizer.webex.runner import WebexRunner

        # Mock transcript endpoint to return empty
        responses.add(
            responses.GET,
            "https://webexapis.com/v1/meetingTranscripts",
            json={"items": []},
            status=200,
        )

        runner = WebexRunner(self.config)
        runner.client = WebexClient(self.config, self.mock_webex)

        with patch.object(runner.client, "get_meetings_with_details") as mock_meetings:
            mock_meetings.return_value = []
            runner._fetch_meetings(UTC)
            mock_meetings.assert_called_once()

    def test_meetings_skipped_when_disabled(self) -> None:
        """Runner.run should skip meetings when include_meetings=False."""
        from summarizer.webex.runner import WebexRunner

        config = _make_config(include_meetings=False)
        runner = WebexRunner(config)
        runner.client = WebexClient(config, self.mock_webex)

        # Mock the core workflow to avoid running full pipeline
        with (
            patch.object(runner, "connect"),
            patch.object(runner, "get_activity", return_value=[]),
            patch.object(runner, "get_user_id", return_value="u1"),
            patch.object(runner, "_group_conversations", return_value=[]),
            patch.object(runner, "_fetch_meetings") as mock_fetch,
            patch("summarizer.webex.runner.display_conversations"),
            patch("summarizer.webex.runner.display_conversations_summary"),
            patch("summarizer.webex.runner.ActivityStore"),
        ):
            runner.run(include_meetings=False, force_refresh=True)
            mock_fetch.assert_not_called()

    def test_meeting_failure_does_not_break_conversations(self) -> None:
        """Meeting fetch failure should not raise or break output."""
        from summarizer.webex.runner import WebexRunner

        runner = WebexRunner(self.config)
        runner.client = WebexClient(self.config, self.mock_webex)

        with patch.object(
            runner.client,
            "get_meetings_with_details",
            side_effect=RuntimeError("API down"),
        ):
            # Should not raise
            runner._fetch_meetings(UTC)


# =============================================================================
# Config tests
# =============================================================================


class TestWebexConfigMeetings(unittest.TestCase):
    """Tests for include_meetings in WebexConfig."""

    def test_include_meetings_default_true(self) -> None:
        """include_meetings should default to True."""
        config = WebexConfig(
            user_email="test@example.com",
            target_date=datetime(2024, 6, 1),
            webex_token="tok",
        )
        assert config.include_meetings is True

    def test_include_meetings_can_be_disabled(self) -> None:
        """include_meetings should be settable to False."""
        config = WebexConfig(
            user_email="test@example.com",
            target_date=datetime(2024, 6, 1),
            webex_token="tok",
            include_meetings=False,
        )
        assert config.include_meetings is False
