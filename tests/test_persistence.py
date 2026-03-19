"""Tests for the SQLite persistence layer and JSON export."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from summarizer.common.models import (
    Change,
    ChangeType,
    Conversation,
    Meeting,
    MeetingSummary,
    Message,
    SpaceType,
    Thread,
    TranscriptSnippet,
    User,
)
from summarizer.common.persistence import ActivityStore

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def store(tmp_path: Path) -> ActivityStore:
    """Create an ActivityStore backed by a temp database."""
    return ActivityStore(db_path=tmp_path / "test.db")


@pytest.fixture()
def sample_user_alice() -> User:
    """Sample user: Alice."""
    return User(id="u1", display_name="Alice")


@pytest.fixture()
def sample_user_bob() -> User:
    """Sample user: Bob."""
    return User(id="u2", display_name="Bob")


def _make_message(
    msg_id: str,
    sender: User,
    recipients: list[User],
    content: str = "hello",
    space_id: str = "space1",
    space_type: SpaceType = SpaceType.DM,
    space_name: str = "DM Room",
    timestamp: datetime | None = None,
    thread: Thread | None = None,
    conversation_id: str | None = None,
) -> Message:
    """Helper to create a Message."""
    return Message(
        id=msg_id,
        space_id=space_id,
        space_type=space_type,
        space_name=space_name,
        sender=sender,
        recipients=recipients,
        timestamp=timestamp or datetime(2026, 3, 10, 9, 0, 0, tzinfo=UTC),
        content=content,
        thread=thread,
        conversation_id=conversation_id,
    )


def _make_conversation(
    convo_id: str,
    messages: list[Message],
    participants: list[User],
    space_id: str = "space1",
    space_type: SpaceType = SpaceType.DM,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
    duration_seconds: int | None = 60,
    is_threaded: bool = False,
) -> Conversation:
    """Helper to create a Conversation."""
    return Conversation(
        id=convo_id,
        space_id=space_id,
        space_type=space_type,
        participants=participants,
        messages=messages,
        start_time=start_time or datetime(2026, 3, 10, 9, 0, 0, tzinfo=UTC),
        end_time=end_time or datetime(2026, 3, 10, 9, 1, 0, tzinfo=UTC),
        duration_seconds=duration_seconds,
        is_threaded=is_threaded,
    )


def _make_meeting(
    meeting_id: str = "mtg1",
    host: User | None = None,
    participants: list[User] | None = None,
    summary: MeetingSummary | None = None,
    snippets: list[TranscriptSnippet] | None = None,
) -> Meeting:
    """Helper to create a Meeting."""
    host = host or User(id="host1", display_name="Host")
    return Meeting(
        id=meeting_id,
        title="Standup",
        start_time=datetime(2026, 3, 10, 10, 0, 0, tzinfo=UTC),
        end_time=datetime(2026, 3, 10, 10, 30, 0, tzinfo=UTC),
        duration_seconds=1800,
        host=host,
        participants=participants or [],
        meeting_series_id="series1",
        site_url="https://example.webex.com",
        summary=summary,
        transcript_snippets=snippets or [],
        transcript_id="tid1",
    )


def _make_change(
    change_id: str = "ch1",
    change_type: ChangeType = ChangeType.COMMIT,
    metadata: dict | None = None,
) -> Change:
    """Helper to create a Change."""
    return Change(
        id=change_id,
        type=change_type,
        timestamp=datetime(2026, 3, 10, 14, 0, 0, tzinfo=UTC),
        repo_full_name="org/repo",
        title="fix: resolve auth timeout",
        url="https://github.com/org/repo/commit/abc",
        summary="Fixed the auth timeout issue",
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------


class TestSchema:
    """Tests for database schema creation."""

    def test_creates_tables_on_init(self, store: ActivityStore) -> None:
        """Should create all required tables."""
        tables = {
            row[0]
            for row in store._conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        expected = {
            "fetch_log",
            "users",
            "messages",
            "message_recipients",
            "conversations",
            "conversation_participants",
            "conversation_messages",
            "meetings",
            "meeting_participants",
            "transcript_snippets",
            "changes",
        }
        assert expected.issubset(tables)

    def test_idempotent_schema(self, tmp_path: Path) -> None:
        """Creating store twice on same DB should not error."""
        db = tmp_path / "test.db"
        store1 = ActivityStore(db_path=db)
        store1.close()
        store2 = ActivityStore(db_path=db)
        store2.close()


# ---------------------------------------------------------------------------
# Store/Load roundtrip tests
# ---------------------------------------------------------------------------


class TestConversationRoundtrip:
    """Tests for storing and loading Webex conversations."""

    def test_store_load_conversations(
        self, store: ActivityStore, sample_user_alice: User, sample_user_bob: User
    ) -> None:
        """Conversations should survive a store/load roundtrip."""
        msg1 = _make_message("m1", sample_user_alice, [sample_user_bob], "Hi Bob")
        msg2 = _make_message(
            "m2",
            sample_user_bob,
            [sample_user_alice],
            "Hi Alice",
            timestamp=datetime(2026, 3, 10, 9, 0, 30, tzinfo=UTC),
        )
        convo = _make_conversation(
            "c1", [msg1, msg2], [sample_user_alice, sample_user_bob]
        )

        store.store_webex_conversations("2026-03-10", [convo])
        loaded = store.load_webex_conversations("2026-03-10")

        assert len(loaded) == 1
        assert loaded[0].id == "c1"
        assert len(loaded[0].messages) == 2
        assert loaded[0].messages[0].content == "Hi Bob"
        assert loaded[0].messages[1].content == "Hi Alice"
        assert len(loaded[0].participants) == 2

    def test_message_order_preserved(
        self, store: ActivityStore, sample_user_alice: User, sample_user_bob: User
    ) -> None:
        """Messages should be loaded in the same order they were stored."""
        msgs = [
            _make_message(f"m{i}", sample_user_alice, [sample_user_bob], f"msg {i}")
            for i in range(5)
        ]
        convo = _make_conversation("c1", msgs, [sample_user_alice, sample_user_bob])

        store.store_webex_conversations("2026-03-10", [convo])
        loaded = store.load_webex_conversations("2026-03-10")

        assert [m.content for m in loaded[0].messages] == [
            "msg 0",
            "msg 1",
            "msg 2",
            "msg 3",
            "msg 4",
        ]

    def test_nullable_thread(
        self, store: ActivityStore, sample_user_alice: User, sample_user_bob: User
    ) -> None:
        """Messages without threads should roundtrip with thread=None."""
        msg = _make_message("m1", sample_user_alice, [sample_user_bob])
        convo = _make_conversation("c1", [msg], [sample_user_alice, sample_user_bob])

        store.store_webex_conversations("2026-03-10", [convo])
        loaded = store.load_webex_conversations("2026-03-10")

        assert loaded[0].messages[0].thread is None

    def test_thread_roundtrip(
        self, store: ActivityStore, sample_user_alice: User, sample_user_bob: User
    ) -> None:
        """Messages with threads should roundtrip correctly."""
        thread = Thread(
            id="t1",
            original_post_id="m0",
            original_poster=sample_user_alice,
        )
        msg = _make_message("m1", sample_user_bob, [sample_user_alice], thread=thread)
        convo = _make_conversation("c1", [msg], [sample_user_alice, sample_user_bob])

        store.store_webex_conversations("2026-03-10", [convo])
        loaded = store.load_webex_conversations("2026-03-10")

        assert loaded[0].messages[0].thread is not None
        assert loaded[0].messages[0].thread.id == "t1"
        assert loaded[0].messages[0].thread.original_post_id == "m0"

    def test_special_chars_in_content(
        self, store: ActivityStore, sample_user_alice: User, sample_user_bob: User
    ) -> None:
        """Content with special characters should roundtrip."""
        msg = _make_message(
            "m1",
            sample_user_alice,
            [sample_user_bob],
            'Hello 🎉 "quotes" <html> & stuff\'s',
        )
        convo = _make_conversation("c1", [msg], [sample_user_alice, sample_user_bob])

        store.store_webex_conversations("2026-03-10", [convo])
        loaded = store.load_webex_conversations("2026-03-10")

        assert loaded[0].messages[0].content == 'Hello 🎉 "quotes" <html> & stuff\'s'


class TestMeetingRoundtrip:
    """Tests for storing and loading Webex meetings."""

    def test_store_load_meetings_basic(self, store: ActivityStore) -> None:
        """Basic meeting should survive a store/load roundtrip."""
        meeting = _make_meeting()

        store.store_webex_meetings("2026-03-10", [meeting])
        loaded = store.load_webex_meetings("2026-03-10")

        assert len(loaded) == 1
        assert loaded[0].id == "mtg1"
        assert loaded[0].title == "Standup"
        assert loaded[0].duration_seconds == 1800
        assert loaded[0].host.display_name == "Host"

    def test_store_load_meetings_with_summary(self, store: ActivityStore) -> None:
        """Meeting with AI summary should roundtrip."""
        summary = MeetingSummary(
            overview="Quick standup",
            notes=["Discussed X", "Decided Y"],
            action_items=["Alice: do A", "Bob: do B"],
        )
        meeting = _make_meeting(summary=summary)

        store.store_webex_meetings("2026-03-10", [meeting])
        loaded = store.load_webex_meetings("2026-03-10")

        assert loaded[0].summary is not None
        assert loaded[0].summary.overview == "Quick standup"
        assert loaded[0].summary.notes == ["Discussed X", "Decided Y"]
        assert loaded[0].summary.action_items == ["Alice: do A", "Bob: do B"]

    def test_store_load_meetings_with_transcript(self, store: ActivityStore) -> None:
        """Meeting with transcript snippets should roundtrip."""
        alice = User(id="u1", display_name="Alice")
        snippets = [
            TranscriptSnippet(
                speaker=alice,
                text="Let's start",
                start_time=datetime(2026, 3, 10, 10, 0, 5, tzinfo=UTC),
            ),
            TranscriptSnippet(
                speaker=alice,
                text="Moving on",
                start_time=datetime(2026, 3, 10, 10, 5, 0, tzinfo=UTC),
            ),
        ]
        meeting = _make_meeting(participants=[alice], snippets=snippets)

        store.store_webex_meetings("2026-03-10", [meeting])
        loaded = store.load_webex_meetings("2026-03-10")

        assert len(loaded[0].transcript_snippets) == 2
        assert loaded[0].transcript_snippets[0].text == "Let's start"
        assert loaded[0].transcript_snippets[1].text == "Moving on"

    def test_transcript_order_preserved(self, store: ActivityStore) -> None:
        """Transcript snippets should maintain their order."""
        speaker = User(id="u1", display_name="Speaker")
        snippets = [
            TranscriptSnippet(speaker=speaker, text=f"Line {i}") for i in range(5)
        ]
        meeting = _make_meeting(snippets=snippets)

        store.store_webex_meetings("2026-03-10", [meeting])
        loaded = store.load_webex_meetings("2026-03-10")

        assert [s.text for s in loaded[0].transcript_snippets] == [
            "Line 0",
            "Line 1",
            "Line 2",
            "Line 3",
            "Line 4",
        ]

    def test_nullable_summary(self, store: ActivityStore) -> None:
        """Meeting without summary should roundtrip with summary=None."""
        meeting = _make_meeting(summary=None)

        store.store_webex_meetings("2026-03-10", [meeting])
        loaded = store.load_webex_meetings("2026-03-10")

        assert loaded[0].summary is None

    def test_nullable_start_time_on_snippet(self, store: ActivityStore) -> None:
        """Transcript snippet without start_time should roundtrip as None."""
        speaker = User(id="u1", display_name="Speaker")
        snippet = TranscriptSnippet(speaker=speaker, text="Hello", start_time=None)
        meeting = _make_meeting(snippets=[snippet])

        store.store_webex_meetings("2026-03-10", [meeting])
        loaded = store.load_webex_meetings("2026-03-10")

        assert loaded[0].transcript_snippets[0].start_time is None


class TestGithubChangesRoundtrip:
    """Tests for storing and loading GitHub changes."""

    def test_store_load_github_changes(self, store: ActivityStore) -> None:
        """GitHub changes should survive a store/load roundtrip."""
        change = _make_change()

        store.store_github_changes("2026-03-10", [change])
        loaded = store.load_github_changes("2026-03-10")

        assert len(loaded) == 1
        assert loaded[0].id == "ch1"
        assert loaded[0].type == ChangeType.COMMIT
        assert loaded[0].repo_full_name == "org/repo"
        assert loaded[0].title == "fix: resolve auth timeout"
        assert loaded[0].summary == "Fixed the auth timeout issue"

    def test_store_load_github_changes_with_metadata(
        self, store: ActivityStore
    ) -> None:
        """Changes with metadata dict should roundtrip."""
        meta = {"sha": "abc123", "branch": "main", "files_changed": "3"}
        change = _make_change(metadata=meta)

        store.store_github_changes("2026-03-10", [change])
        loaded = store.load_github_changes("2026-03-10")

        assert loaded[0].metadata == meta

    def test_large_metadata_dict(self, store: ActivityStore) -> None:
        """Large metadata dicts should roundtrip."""
        meta = {f"key_{i}": f"value_{i}" for i in range(100)}
        change = _make_change(metadata=meta)

        store.store_github_changes("2026-03-10", [change])
        loaded = store.load_github_changes("2026-03-10")

        assert loaded[0].metadata == meta


# ---------------------------------------------------------------------------
# Cache query tests
# ---------------------------------------------------------------------------


class TestCacheQueries:
    """Tests for cache hit/miss detection."""

    def test_has_webex_data_empty(self, store: ActivityStore) -> None:
        """Should return False when no data stored."""
        assert store.has_webex_data("2026-03-10") is False

    def test_has_webex_data_after_store(
        self, store: ActivityStore, sample_user_alice: User, sample_user_bob: User
    ) -> None:
        """Should return True after storing data."""
        msg = _make_message("m1", sample_user_alice, [sample_user_bob])
        convo = _make_conversation("c1", [msg], [sample_user_alice, sample_user_bob])
        store.store_webex_conversations("2026-03-10", [convo])

        assert store.has_webex_data("2026-03-10") is True
        assert store.has_webex_data("2026-03-11") is False

    def test_has_github_data(self, store: ActivityStore) -> None:
        """Should detect GitHub data correctly."""
        assert store.has_github_data("2026-03-10") is False

        store.store_github_changes("2026-03-10", [_make_change()])
        assert store.has_github_data("2026-03-10") is True

    def test_get_fetch_timestamp(self, store: ActivityStore) -> None:
        """Should return the fetch timestamp for a stored entry."""
        store.store_github_changes("2026-03-10", [_make_change()])

        ts = store.get_fetch_timestamp("2026-03-10", "github")
        assert ts is not None
        assert isinstance(ts, datetime)
        # Should be recent (within the last minute)
        assert (datetime.now(UTC) - ts).total_seconds() < 60

    def test_get_fetch_timestamp_missing(self, store: ActivityStore) -> None:
        """Should return None for missing entries."""
        assert store.get_fetch_timestamp("2026-03-10", "webex") is None


# ---------------------------------------------------------------------------
# Invalidation tests
# ---------------------------------------------------------------------------


class TestInvalidation:
    """Tests for cache invalidation."""

    def test_clear_date_all(
        self, store: ActivityStore, sample_user_alice: User, sample_user_bob: User
    ) -> None:
        """Clearing all platforms for a date should remove everything."""
        msg = _make_message("m1", sample_user_alice, [sample_user_bob])
        convo = _make_conversation("c1", [msg], [sample_user_alice, sample_user_bob])
        store.store_webex_conversations("2026-03-10", [convo])
        store.store_github_changes("2026-03-10", [_make_change()])

        store.clear_date("2026-03-10")

        assert store.has_webex_data("2026-03-10") is False
        assert store.has_github_data("2026-03-10") is False
        assert store.load_webex_conversations("2026-03-10") == []
        assert store.load_github_changes("2026-03-10") == []

    def test_clear_date_specific_platform(
        self, store: ActivityStore, sample_user_alice: User, sample_user_bob: User
    ) -> None:
        """Clearing a specific platform should leave the other intact."""
        msg = _make_message("m1", sample_user_alice, [sample_user_bob])
        convo = _make_conversation("c1", [msg], [sample_user_alice, sample_user_bob])
        store.store_webex_conversations("2026-03-10", [convo])
        store.store_github_changes("2026-03-10", [_make_change()])

        store.clear_date("2026-03-10", platform="github")

        assert store.has_webex_data("2026-03-10") is True
        assert store.has_github_data("2026-03-10") is False

    def test_store_overwrites_existing(
        self, store: ActivityStore, sample_user_alice: User, sample_user_bob: User
    ) -> None:
        """Storing data for a date that already has data should replace it."""
        msg1 = _make_message("m1", sample_user_alice, [sample_user_bob], "original")
        convo1 = _make_conversation("c1", [msg1], [sample_user_alice, sample_user_bob])
        store.store_webex_conversations("2026-03-10", [convo1])

        msg2 = _make_message("m2", sample_user_bob, [sample_user_alice], "updated")
        convo2 = _make_conversation("c2", [msg2], [sample_user_alice, sample_user_bob])
        store.store_webex_conversations("2026-03-10", [convo2])

        loaded = store.load_webex_conversations("2026-03-10")
        assert len(loaded) == 1
        assert loaded[0].id == "c2"
        assert loaded[0].messages[0].content == "updated"


# ---------------------------------------------------------------------------
# JSON export tests
# ---------------------------------------------------------------------------


class TestJsonExport:
    """Tests for JSON export functionality."""

    def test_export_creates_file(
        self,
        store: ActivityStore,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Export should create a JSON file."""
        monkeypatch.setattr(
            "summarizer.common.persistence.EXPORTS_DIR", tmp_path / "exports"
        )
        path = store.export_json("2026-03-10", conversations=[], meetings=[])
        assert path.exists()
        assert path.suffix == ".json"

    def test_export_valid_json(
        self,
        store: ActivityStore,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Exported file should be valid JSON."""
        monkeypatch.setattr(
            "summarizer.common.persistence.EXPORTS_DIR", tmp_path / "exports"
        )
        path = store.export_json("2026-03-10", conversations=[], meetings=[])
        data = json.loads(path.read_text())
        assert isinstance(data, dict)

    def test_export_structure(
        self,
        store: ActivityStore,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        sample_user_alice: User,
        sample_user_bob: User,
    ) -> None:
        """Exported JSON should have the expected top-level structure."""
        monkeypatch.setattr(
            "summarizer.common.persistence.EXPORTS_DIR", tmp_path / "exports"
        )
        msg = _make_message("m1", sample_user_alice, [sample_user_bob])
        convo = _make_conversation("c1", [msg], [sample_user_alice, sample_user_bob])

        path = store.export_json(
            "2026-03-10",
            conversations=[convo],
            meetings=[_make_meeting()],
            changes=[_make_change()],
        )
        data = json.loads(path.read_text())

        assert data["date"] == "2026-03-10"
        assert "exported_at" in data
        assert "webex" in data
        assert "github" in data
        assert "conversations" in data["webex"]
        assert "meetings" in data["webex"]
        assert "changes" in data["github"]

    def test_export_merges_platforms(
        self,
        store: ActivityStore,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Running export twice (webex then github) should merge into one file."""
        monkeypatch.setattr(
            "summarizer.common.persistence.EXPORTS_DIR", tmp_path / "exports"
        )
        # First export: webex only
        store.export_json("2026-03-10", conversations=[], meetings=[])

        # Second export: github only
        store.export_json("2026-03-10", changes=[_make_change()])

        path = tmp_path / "exports" / "2026-03-10.json"
        data = json.loads(path.read_text())

        assert "webex" in data
        assert "github" in data
        assert data["webex"]["conversations"] == []
        assert len(data["github"]["changes"]) == 1

    def test_export_datetimes_iso8601(
        self,
        store: ActivityStore,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        sample_user_alice: User,
        sample_user_bob: User,
    ) -> None:
        """Datetimes in export should be ISO 8601 strings."""
        monkeypatch.setattr(
            "summarizer.common.persistence.EXPORTS_DIR", tmp_path / "exports"
        )
        msg = _make_message("m1", sample_user_alice, [sample_user_bob])
        convo = _make_conversation("c1", [msg], [sample_user_alice, sample_user_bob])

        path = store.export_json("2026-03-10", conversations=[convo])
        data = json.loads(path.read_text())

        convo_data = data["webex"]["conversations"][0]
        # Should be parseable as ISO 8601
        datetime.fromisoformat(convo_data["start_time"])
        datetime.fromisoformat(convo_data["end_time"])
        datetime.fromisoformat(convo_data["messages"][0]["timestamp"])


# ---------------------------------------------------------------------------
# Edge case tests
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Tests for edge cases."""

    def test_empty_conversation_list(self, store: ActivityStore) -> None:
        """Storing an empty conversation list should still update fetch_log."""
        store.store_webex_conversations("2026-03-10", [])
        assert store.has_webex_data("2026-03-10") is True
        assert store.load_webex_conversations("2026-03-10") == []

    def test_empty_changes_list(self, store: ActivityStore) -> None:
        """Storing an empty changes list should still update fetch_log."""
        store.store_github_changes("2026-03-10", [])
        assert store.has_github_data("2026-03-10") is True
        assert store.load_github_changes("2026-03-10") == []

    def test_user_deduplication(
        self, store: ActivityStore, sample_user_alice: User, sample_user_bob: User
    ) -> None:
        """Same user appearing in multiple conversations should be deduplicated."""
        msg1 = _make_message("m1", sample_user_alice, [sample_user_bob])
        msg2 = _make_message("m2", sample_user_alice, [sample_user_bob], space_id="s2")
        convo1 = _make_conversation("c1", [msg1], [sample_user_alice, sample_user_bob])
        convo2 = _make_conversation(
            "c2",
            [msg2],
            [sample_user_alice, sample_user_bob],
            space_id="s2",
        )

        store.store_webex_conversations("2026-03-10", [convo1, convo2])

        # Should not raise any unique constraint errors
        loaded = store.load_webex_conversations("2026-03-10")
        assert len(loaded) == 2

        # Verify user is only stored once
        user_count = store._conn.execute(
            "SELECT COUNT(*) FROM users WHERE id = ?", ("u1",)
        ).fetchone()[0]
        assert user_count == 1

    def test_load_from_empty_date(self, store: ActivityStore) -> None:
        """Loading from a date with no data should return empty lists."""
        assert store.load_webex_conversations("2099-01-01") == []
        assert store.load_webex_meetings("2099-01-01") == []
        assert store.load_github_changes("2099-01-01") == []

    def test_multiple_dates_isolated(
        self, store: ActivityStore, sample_user_alice: User, sample_user_bob: User
    ) -> None:
        """Data for different dates should be isolated."""
        msg1 = _make_message("m1", sample_user_alice, [sample_user_bob], "day 1")
        convo1 = _make_conversation("c1", [msg1], [sample_user_alice, sample_user_bob])

        msg2 = _make_message("m2", sample_user_alice, [sample_user_bob], "day 2")
        convo2 = _make_conversation("c2", [msg2], [sample_user_alice, sample_user_bob])

        store.store_webex_conversations("2026-03-10", [convo1])
        store.store_webex_conversations("2026-03-11", [convo2])

        day1 = store.load_webex_conversations("2026-03-10")
        day2 = store.load_webex_conversations("2026-03-11")

        assert len(day1) == 1
        assert day1[0].messages[0].content == "day 1"
        assert len(day2) == 1
        assert day2[0].messages[0].content == "day 2"


# ---------------------------------------------------------------------------
# Full transcript + complete summary tests
# ---------------------------------------------------------------------------


class TestFullTranscriptAndSummary:
    """Tests for full VTT transcript and raw summary JSON fields."""

    def test_store_load_meetings_with_vtt(self, store: ActivityStore) -> None:
        """Meeting with a VTT transcript should roundtrip."""
        vtt_content = (
            "WEBVTT\n\n"
            "00:00:00.000 --> 00:00:05.000\n"
            "Alice: Hello everyone\n\n"
            "00:00:05.000 --> 00:00:10.000\n"
            "Bob: Hi Alice, let's get started\n"
        )
        meeting = _make_meeting()
        meeting.transcript_vtt = vtt_content

        store.store_webex_meetings("2026-03-10", [meeting])
        loaded = store.load_webex_meetings("2026-03-10")

        assert len(loaded) == 1
        assert loaded[0].transcript_vtt == vtt_content

    def test_store_load_meetings_with_raw_summary_json(
        self, store: ActivityStore
    ) -> None:
        """Meeting with raw summary JSON should roundtrip."""
        raw_json = {
            "meetingId": "mtg1",
            "overview": "Quick standup",
            "notes": ["Discussed X"],
            "actionItems": ["Alice: do A"],
            "extraField": "preserved for RAG",
            "nestedData": {"key": "value", "list": [1, 2, 3]},
        }
        summary = MeetingSummary(
            overview="Quick standup",
            notes=["Discussed X"],
            action_items=["Alice: do A"],
            raw_json=raw_json,
        )
        meeting = _make_meeting(summary=summary)

        store.store_webex_meetings("2026-03-10", [meeting])
        loaded = store.load_webex_meetings("2026-03-10")

        assert loaded[0].summary is not None
        assert loaded[0].summary.raw_json == raw_json
        assert loaded[0].summary.raw_json["extraField"] == "preserved for RAG"

    def test_vtt_none_when_not_set(self, store: ActivityStore) -> None:
        """Meeting without VTT should have transcript_vtt=None."""
        meeting = _make_meeting()  # transcript_vtt defaults to None

        store.store_webex_meetings("2026-03-10", [meeting])
        loaded = store.load_webex_meetings("2026-03-10")

        assert loaded[0].transcript_vtt is None

    def test_raw_json_none_when_no_summary(self, store: ActivityStore) -> None:
        """Meeting without summary should not have raw_json."""
        meeting = _make_meeting(summary=None)

        store.store_webex_meetings("2026-03-10", [meeting])
        loaded = store.load_webex_meetings("2026-03-10")

        assert loaded[0].summary is None

    def test_raw_json_none_when_summary_has_no_raw(self, store: ActivityStore) -> None:
        """Summary without raw_json should roundtrip with raw_json=None."""
        summary = MeetingSummary(
            overview="Overview",
            notes=["Note 1"],
            action_items=[],
            raw_json=None,
        )
        meeting = _make_meeting(summary=summary)

        store.store_webex_meetings("2026-03-10", [meeting])
        loaded = store.load_webex_meetings("2026-03-10")

        assert loaded[0].summary is not None
        assert loaded[0].summary.raw_json is None

    def test_migration_adds_columns(self, tmp_path: Path) -> None:
        """Idempotent migration should add new columns to existing DB."""
        db = tmp_path / "test.db"
        # Create the store (creates schema with new columns)
        store1 = ActivityStore(db_path=db)
        store1.close()

        # Open again — should not fail on migration
        store2 = ActivityStore(db_path=db)

        # Verify columns exist by inserting a meeting with the new fields
        meeting = _make_meeting()
        meeting.transcript_vtt = "WEBVTT\n\ntest"
        meeting.summary = MeetingSummary(overview="test", raw_json={"key": "value"})
        store2.store_webex_meetings("2026-03-10", [meeting])
        loaded = store2.load_webex_meetings("2026-03-10")

        assert loaded[0].transcript_vtt == "WEBVTT\n\ntest"
        assert loaded[0].summary.raw_json == {"key": "value"}
        store2.close()

    def test_json_export_includes_vtt_and_raw_json(
        self,
        store: ActivityStore,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """JSON export should include transcript_vtt and summary.raw_json."""
        monkeypatch.setattr(
            "summarizer.common.persistence.EXPORTS_DIR", tmp_path / "exports"
        )
        raw_json = {"overview": "Test", "extra": "data"}
        summary = MeetingSummary(
            overview="Test",
            notes=[],
            action_items=[],
            raw_json=raw_json,
        )
        meeting = _make_meeting(summary=summary)
        meeting.transcript_vtt = "WEBVTT\n\nsome content"

        path = store.export_json("2026-03-10", meetings=[meeting])
        data = json.loads(path.read_text())

        meeting_data = data["webex"]["meetings"][0]
        assert meeting_data["transcript_vtt"] == "WEBVTT\n\nsome content"
        assert meeting_data["summary"]["raw_json"] == raw_json
