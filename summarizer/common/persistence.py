"""SQLite persistence layer and JSON export for activity data.

Provides a read-through cache keyed by date. When the CLI runs for a date,
all API results (Webex conversations, meetings, GitHub changes) are stored
in a local SQLite database. Re-running for the same date pulls from the
database instead of making live API calls.

Every run also exports a JSON file alongside the DB for future RAG
consumption.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

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

logger = logging.getLogger(__name__)

# Default paths under ~/.config/summarizer/
_CONFIG_DIR = Path.home() / ".config" / "summarizer"
DB_PATH = _CONFIG_DIR / "activity.db"
EXPORTS_DIR = _CONFIG_DIR / "exports"

# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------

_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS fetch_log (
    date     TEXT NOT NULL,
    platform TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (date, platform)
);

CREATE TABLE IF NOT EXISTS users (
    id           TEXT PRIMARY KEY,
    display_name TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id                        TEXT PRIMARY KEY,
    date                      TEXT NOT NULL,
    space_id                  TEXT NOT NULL,
    space_type                TEXT NOT NULL,
    space_name                TEXT NOT NULL,
    sender_id                 TEXT NOT NULL REFERENCES users(id),
    timestamp                 TEXT NOT NULL,
    content                   TEXT NOT NULL,
    thread_id                 TEXT,
    thread_original_post_id   TEXT,
    thread_original_poster_id TEXT,
    conversation_id           TEXT
);

CREATE INDEX IF NOT EXISTS idx_messages_date  ON messages(date);
CREATE INDEX IF NOT EXISTS idx_messages_space ON messages(space_id);

CREATE TABLE IF NOT EXISTS message_recipients (
    message_id TEXT NOT NULL REFERENCES messages(id),
    user_id    TEXT NOT NULL REFERENCES users(id),
    PRIMARY KEY (message_id, user_id)
);

CREATE TABLE IF NOT EXISTS conversations (
    id               TEXT PRIMARY KEY,
    date             TEXT NOT NULL,
    space_id         TEXT NOT NULL,
    space_type       TEXT NOT NULL,
    start_time       TEXT,
    end_time         TEXT,
    duration_seconds INTEGER,
    is_threaded      INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_conversations_date ON conversations(date);

CREATE TABLE IF NOT EXISTS conversation_participants (
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    user_id         TEXT NOT NULL REFERENCES users(id),
    PRIMARY KEY (conversation_id, user_id)
);

CREATE TABLE IF NOT EXISTS conversation_messages (
    conversation_id TEXT NOT NULL REFERENCES conversations(id),
    message_id      TEXT NOT NULL REFERENCES messages(id),
    position        INTEGER NOT NULL,
    PRIMARY KEY (conversation_id, message_id)
);

CREATE TABLE IF NOT EXISTS meetings (
    id                   TEXT PRIMARY KEY,
    date                 TEXT NOT NULL,
    title                TEXT NOT NULL,
    start_time           TEXT NOT NULL,
    end_time             TEXT NOT NULL,
    duration_seconds     INTEGER NOT NULL,
    host_id              TEXT NOT NULL REFERENCES users(id),
    meeting_series_id    TEXT,
    site_url             TEXT,
    transcript_id        TEXT,
    summary_overview     TEXT,
    summary_notes        TEXT,
    summary_action_items TEXT
);

CREATE INDEX IF NOT EXISTS idx_meetings_date ON meetings(date);

CREATE TABLE IF NOT EXISTS meeting_participants (
    meeting_id TEXT NOT NULL REFERENCES meetings(id),
    user_id    TEXT NOT NULL REFERENCES users(id),
    PRIMARY KEY (meeting_id, user_id)
);

CREATE TABLE IF NOT EXISTS transcript_snippets (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL REFERENCES meetings(id),
    speaker_id TEXT NOT NULL REFERENCES users(id),
    text       TEXT NOT NULL,
    start_time TEXT,
    position   INTEGER NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_snippets_meeting ON transcript_snippets(meeting_id);

CREATE TABLE IF NOT EXISTS changes (
    id             TEXT PRIMARY KEY,
    date           TEXT NOT NULL,
    type           TEXT NOT NULL,
    timestamp      TEXT NOT NULL,
    repo_full_name TEXT NOT NULL,
    title          TEXT NOT NULL,
    url            TEXT NOT NULL,
    summary        TEXT,
    metadata       TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_changes_date ON changes(date);
CREATE INDEX IF NOT EXISTS idx_changes_repo ON changes(repo_full_name);
"""


class ActivityStore:
    """SQLite-backed cache and JSON exporter for daily activity data."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        """Initialize the store, creating the database and schema if needed."""
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._create_schema()

    # ------------------------------------------------------------------
    # Schema bootstrapping
    # ------------------------------------------------------------------

    def _create_schema(self) -> None:
        """Create all tables and indexes (idempotent)."""
        self._conn.executescript(_SCHEMA_SQL)

        # Idempotent migration: add columns for full transcript + raw summary
        for col, col_type in [
            ("transcript_vtt", "TEXT"),
            ("summary_raw_json", "TEXT"),
        ]:
            try:
                self._conn.execute(f"ALTER TABLE meetings ADD COLUMN {col} {col_type}")
            except sqlite3.OperationalError:
                pass  # Column already exists

    # ------------------------------------------------------------------
    # Cache queries
    # ------------------------------------------------------------------

    def has_webex_data(self, date: str) -> bool:
        """Check if Webex data exists for a given date."""
        row = self._conn.execute(
            "SELECT 1 FROM fetch_log WHERE date = ? AND platform = 'webex'",
            (date,),
        ).fetchone()
        return row is not None

    def has_github_data(self, date: str) -> bool:
        """Check if GitHub data exists for a given date."""
        row = self._conn.execute(
            "SELECT 1 FROM fetch_log WHERE date = ? AND platform = 'github'",
            (date,),
        ).fetchone()
        return row is not None

    def get_fetch_timestamp(self, date: str, platform: str) -> datetime | None:
        """Get the timestamp when data was fetched for a date+platform."""
        row = self._conn.execute(
            "SELECT fetched_at FROM fetch_log WHERE date = ? AND platform = ?",
            (date, platform),
        ).fetchone()
        if row is None:
            return None
        return datetime.fromisoformat(row["fetched_at"])

    # ------------------------------------------------------------------
    # User helpers (deduplication)
    # ------------------------------------------------------------------

    def _upsert_user(self, user: User) -> None:
        """Insert or update a user record."""
        self._conn.execute(
            "INSERT OR REPLACE INTO users (id, display_name) VALUES (?, ?)",
            (user.id, user.display_name),
        )

    def _load_user(self, user_id: str) -> User:
        """Load a user by ID."""
        row = self._conn.execute(
            "SELECT id, display_name FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return User(id=user_id, display_name="Unknown")
        return User(id=row["id"], display_name=row["display_name"])

    # ------------------------------------------------------------------
    # Store: Webex conversations (messages included)
    # ------------------------------------------------------------------

    def store_webex_conversations(
        self, date: str, conversations: list[Conversation]
    ) -> None:
        """Store Webex conversations and their messages for a date.

        Replaces any existing data for this date.
        """
        now = datetime.now(UTC).isoformat()
        cur = self._conn.cursor()
        try:
            cur.execute("BEGIN")

            # Clear existing data for this date
            self._clear_webex_data(cur, date)

            for convo in conversations:
                # Prefix conversation ID with date to ensure global
                # uniqueness across days (e.g. "dm-jane-1" → "2026-03-10/dm-jane-1")
                db_convo_id = f"{date}/{convo.id}"

                # Upsert participants
                for user in convo.participants:
                    self._upsert_user(user)

                # Insert conversation
                cur.execute(
                    """INSERT INTO conversations
                       (id, date, space_id, space_type, start_time, end_time,
                        duration_seconds, is_threaded)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        db_convo_id,
                        date,
                        convo.space_id,
                        convo.space_type.value,
                        convo.start_time.isoformat() if convo.start_time else None,
                        convo.end_time.isoformat() if convo.end_time else None,
                        convo.duration_seconds,
                        1 if convo.is_threaded else 0,
                    ),
                )

                # Insert conversation participants
                for user in convo.participants:
                    cur.execute(
                        """INSERT OR IGNORE INTO conversation_participants
                           (conversation_id, user_id) VALUES (?, ?)""",
                        (db_convo_id, user.id),
                    )

                # Insert messages
                for pos, msg in enumerate(convo.messages):
                    self._upsert_user(msg.sender)
                    for recip in msg.recipients:
                        self._upsert_user(recip)

                    cur.execute(
                        """INSERT OR IGNORE INTO messages
                           (id, date, space_id, space_type, space_name, sender_id,
                            timestamp, content, thread_id, thread_original_post_id,
                            thread_original_poster_id, conversation_id)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            msg.id,
                            date,
                            msg.space_id,
                            msg.space_type.value,
                            msg.space_name,
                            msg.sender.id,
                            msg.timestamp.isoformat(),
                            msg.content,
                            msg.thread.id if msg.thread else None,
                            msg.thread.original_post_id if msg.thread else None,
                            msg.thread.original_poster.id if msg.thread else None,
                            db_convo_id,
                        ),
                    )

                    # Insert recipients
                    for recip in msg.recipients:
                        cur.execute(
                            """INSERT OR IGNORE INTO message_recipients
                               (message_id, user_id) VALUES (?, ?)""",
                            (msg.id, recip.id),
                        )

                    # Link message to conversation
                    cur.execute(
                        """INSERT OR IGNORE INTO conversation_messages
                           (conversation_id, message_id, position)
                           VALUES (?, ?, ?)""",
                        (db_convo_id, msg.id, pos),
                    )

            # Update fetch log
            cur.execute(
                """INSERT OR REPLACE INTO fetch_log (date, platform, fetched_at)
                   VALUES (?, 'webex', ?)""",
                (date, now),
            )
            self._conn.commit()
            logger.info(
                "Stored %d Webex conversations for %s", len(conversations), date
            )

        except Exception:
            self._conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Store: Webex meetings
    # ------------------------------------------------------------------

    def store_webex_meetings(self, date: str, meetings: list[Meeting]) -> None:
        """Store Webex meetings for a date. Replaces existing meeting data."""
        now = datetime.now(UTC).isoformat()
        cur = self._conn.cursor()
        try:
            cur.execute("BEGIN")

            # Clear existing meetings for this date
            self._clear_meeting_data(cur, date)

            # Defense-in-depth: skip any meeting whose actual start date does
            # not match the sync's target date. The upstream Webex meetings
            # API has historically returned extra meetings outside the
            # requested window (meetingType=meeting ignores from/to filters),
            # and silently storing those under the sync date would duplicate
            # them across every subsequent day's sync.
            filtered_meetings: list[Meeting] = []
            for meeting in meetings:
                actual_date = meeting.start_time.date().isoformat()
                if actual_date != date:
                    logger.warning(
                        "Skipping meeting '%s' (id=%s) for date %s — "
                        "actual start date is %s",
                        meeting.title,
                        meeting.id,
                        date,
                        actual_date,
                    )
                    continue
                filtered_meetings.append(meeting)
            meetings = filtered_meetings

            for meeting in meetings:
                # Prefix meeting ID with date to ensure global uniqueness
                # (recurring meetings share the same series ID across days)
                db_meeting_id = f"{date}/{meeting.id}"

                self._upsert_user(meeting.host)
                for p in meeting.participants:
                    self._upsert_user(p)

                summary_notes = None
                summary_action_items = None
                summary_overview = None
                summary_raw_json = None
                if meeting.summary:
                    summary_overview = meeting.summary.overview
                    summary_notes = json.dumps(meeting.summary.notes)
                    summary_action_items = json.dumps(meeting.summary.action_items)
                    if meeting.summary.raw_json:
                        summary_raw_json = json.dumps(meeting.summary.raw_json)

                cur.execute(
                    """INSERT INTO meetings
                       (id, date, title, start_time, end_time, duration_seconds,
                        host_id, meeting_series_id, site_url, transcript_id,
                        summary_overview, summary_notes, summary_action_items,
                        transcript_vtt, summary_raw_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        db_meeting_id,
                        date,
                        meeting.title,
                        meeting.start_time.isoformat(),
                        meeting.end_time.isoformat(),
                        meeting.duration_seconds,
                        meeting.host.id,
                        meeting.meeting_series_id,
                        meeting.site_url,
                        meeting.transcript_id,
                        summary_overview,
                        summary_notes,
                        summary_action_items,
                        meeting.transcript_vtt,
                        summary_raw_json,
                    ),
                )

                # Participants
                for p in meeting.participants:
                    cur.execute(
                        """INSERT OR IGNORE INTO meeting_participants
                           (meeting_id, user_id) VALUES (?, ?)""",
                        (db_meeting_id, p.id),
                    )

                # Transcript snippets
                for pos, snippet in enumerate(meeting.transcript_snippets):
                    self._upsert_user(snippet.speaker)
                    cur.execute(
                        """INSERT INTO transcript_snippets
                           (meeting_id, speaker_id, text, start_time, position)
                           VALUES (?, ?, ?, ?, ?)""",
                        (
                            db_meeting_id,
                            snippet.speaker.id,
                            snippet.text,
                            snippet.start_time.isoformat()
                            if snippet.start_time
                            else None,
                            pos,
                        ),
                    )

            # Update fetch log — mark meetings as part of webex platform.
            # Meetings share the webex fetch_log entry set in
            # store_webex_conversations. Only update if no entry yet.
            cur.execute(
                """INSERT OR IGNORE INTO fetch_log (date, platform, fetched_at)
                   VALUES (?, 'webex', ?)""",
                (date, now),
            )
            self._conn.commit()
            logger.info("Stored %d Webex meetings for %s", len(meetings), date)

        except Exception:
            self._conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Store: GitHub changes
    # ------------------------------------------------------------------

    def store_github_changes(self, date: str, changes: list[Change]) -> None:
        """Store GitHub changes for a date. Replaces existing data."""
        now = datetime.now(UTC).isoformat()
        cur = self._conn.cursor()
        try:
            cur.execute("BEGIN")

            # Clear existing changes for this date
            cur.execute("DELETE FROM changes WHERE date = ?", (date,))

            for change in changes:
                cur.execute(
                    """INSERT INTO changes
                       (id, date, type, timestamp, repo_full_name, title,
                        url, summary, metadata)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        change.id,
                        date,
                        change.type.value,
                        change.timestamp.isoformat(),
                        change.repo_full_name,
                        change.title,
                        change.url,
                        change.summary,
                        json.dumps(change.metadata),
                    ),
                )

            # Update fetch log
            cur.execute(
                """INSERT OR REPLACE INTO fetch_log (date, platform, fetched_at)
                   VALUES (?, 'github', ?)""",
                (date, now),
            )
            self._conn.commit()
            logger.info("Stored %d GitHub changes for %s", len(changes), date)

        except Exception:
            self._conn.rollback()
            raise

    # ------------------------------------------------------------------
    # Load: Webex conversations
    # ------------------------------------------------------------------

    def load_webex_conversations(self, date: str) -> list[Conversation]:
        """Load Webex conversations for a date from the database."""
        rows = self._conn.execute(
            """SELECT id, space_id, space_type, start_time, end_time,
                      duration_seconds, is_threaded
               FROM conversations WHERE date = ?
               ORDER BY start_time""",
            (date,),
        ).fetchall()

        conversations: list[Conversation] = []
        for row in rows:
            db_convo_id = row["id"]
            # Strip the date prefix added during storage
            # ("2026-03-10/dm-jane-1" → "dm-jane-1")
            convo_id = (
                db_convo_id.split("/", 1)[1] if "/" in db_convo_id else db_convo_id
            )

            # Load participants
            participants = self._load_conversation_participants(db_convo_id)

            # Load messages in order
            messages = self._load_conversation_messages(db_convo_id, convo_id)

            conversations.append(
                Conversation(
                    id=convo_id,
                    space_id=row["space_id"],
                    space_type=SpaceType(row["space_type"]),
                    participants=participants,
                    messages=messages,
                    start_time=(
                        datetime.fromisoformat(row["start_time"])
                        if row["start_time"]
                        else None
                    ),
                    end_time=(
                        datetime.fromisoformat(row["end_time"])
                        if row["end_time"]
                        else None
                    ),
                    duration_seconds=row["duration_seconds"],
                    is_threaded=bool(row["is_threaded"]),
                )
            )

        return conversations

    def _load_conversation_participants(self, convo_id: str) -> list[User]:
        """Load participants for a conversation."""
        rows = self._conn.execute(
            """SELECT u.id, u.display_name
               FROM conversation_participants cp
               JOIN users u ON cp.user_id = u.id
               WHERE cp.conversation_id = ?""",
            (convo_id,),
        ).fetchall()
        return [User(id=r["id"], display_name=r["display_name"]) for r in rows]

    def _load_conversation_messages(
        self, db_convo_id: str, model_convo_id: str
    ) -> list[Message]:
        """Load messages for a conversation in positional order."""
        rows = self._conn.execute(
            """SELECT m.id, m.space_id, m.space_type, m.space_name,
                      m.sender_id, m.timestamp, m.content,
                      m.thread_id, m.thread_original_post_id,
                      m.thread_original_poster_id
               FROM conversation_messages cm
               JOIN messages m ON cm.message_id = m.id
               WHERE cm.conversation_id = ?
               ORDER BY cm.position""",
            (db_convo_id,),
        ).fetchall()

        messages: list[Message] = []
        for r in rows:
            sender = self._load_user(r["sender_id"])

            # Load recipients
            recip_rows = self._conn.execute(
                """SELECT u.id, u.display_name
                   FROM message_recipients mr
                   JOIN users u ON mr.user_id = u.id
                   WHERE mr.message_id = ?""",
                (r["id"],),
            ).fetchall()
            recipients = [
                User(id=rr["id"], display_name=rr["display_name"]) for rr in recip_rows
            ]

            # Reconstruct thread if present
            thread = None
            if r["thread_id"]:
                thread = Thread(
                    id=r["thread_id"],
                    original_post_id=r["thread_original_post_id"] or "",
                    original_poster=self._load_user(
                        r["thread_original_poster_id"] or ""
                    ),
                )

            messages.append(
                Message(
                    id=r["id"],
                    space_id=r["space_id"],
                    space_type=SpaceType(r["space_type"]),
                    space_name=r["space_name"],
                    sender=sender,
                    recipients=recipients,
                    timestamp=datetime.fromisoformat(r["timestamp"]),
                    content=r["content"],
                    thread=thread,
                    conversation_id=model_convo_id,
                )
            )

        return messages

    # ------------------------------------------------------------------
    # Load: Webex meetings
    # ------------------------------------------------------------------

    def load_webex_meetings(self, date: str) -> list[Meeting]:
        """Load Webex meetings for a date from the database."""
        rows = self._conn.execute(
            """SELECT id, title, start_time, end_time, duration_seconds,
                      host_id, meeting_series_id, site_url, transcript_id,
                      summary_overview, summary_notes, summary_action_items,
                      transcript_vtt, summary_raw_json
               FROM meetings WHERE date = ?
               ORDER BY start_time""",
            (date,),
        ).fetchall()

        meetings: list[Meeting] = []
        for row in rows:
            db_meeting_id = row["id"]
            # Strip the date prefix added during storage
            meeting_id = (
                db_meeting_id.split("/", 1)[1]
                if "/" in db_meeting_id
                else db_meeting_id
            )
            host = self._load_user(row["host_id"])

            # Load participants
            p_rows = self._conn.execute(
                """SELECT u.id, u.display_name
                   FROM meeting_participants mp
                   JOIN users u ON mp.user_id = u.id
                   WHERE mp.meeting_id = ?""",
                (db_meeting_id,),
            ).fetchall()
            participants = [
                User(id=pr["id"], display_name=pr["display_name"]) for pr in p_rows
            ]

            # Reconstruct summary
            summary = None
            if row["summary_overview"] is not None:
                raw_json = None
                if row["summary_raw_json"]:
                    raw_json = json.loads(row["summary_raw_json"])
                summary = MeetingSummary(
                    overview=row["summary_overview"] or "",
                    notes=json.loads(row["summary_notes"])
                    if row["summary_notes"]
                    else [],
                    action_items=json.loads(row["summary_action_items"])
                    if row["summary_action_items"]
                    else [],
                    raw_json=raw_json,
                )

            # Load transcript snippets
            t_rows = self._conn.execute(
                """SELECT speaker_id, text, start_time, position
                   FROM transcript_snippets
                   WHERE meeting_id = ?
                   ORDER BY position""",
                (db_meeting_id,),
            ).fetchall()
            snippets = [
                TranscriptSnippet(
                    speaker=self._load_user(tr["speaker_id"]),
                    text=tr["text"],
                    start_time=(
                        datetime.fromisoformat(tr["start_time"])
                        if tr["start_time"]
                        else None
                    ),
                )
                for tr in t_rows
            ]

            meetings.append(
                Meeting(
                    id=meeting_id,
                    title=row["title"],
                    start_time=datetime.fromisoformat(row["start_time"]),
                    end_time=datetime.fromisoformat(row["end_time"]),
                    duration_seconds=row["duration_seconds"],
                    host=host,
                    participants=participants,
                    meeting_series_id=row["meeting_series_id"],
                    site_url=row["site_url"],
                    summary=summary,
                    transcript_snippets=snippets,
                    transcript_id=row["transcript_id"],
                    transcript_vtt=row["transcript_vtt"],
                )
            )

        return meetings

    # ------------------------------------------------------------------
    # Load: GitHub changes
    # ------------------------------------------------------------------

    def load_github_changes(self, date: str) -> list[Change]:
        """Load GitHub changes for a date from the database."""
        rows = self._conn.execute(
            """SELECT id, type, timestamp, repo_full_name, title,
                      url, summary, metadata
               FROM changes WHERE date = ?
               ORDER BY timestamp""",
            (date,),
        ).fetchall()

        return [
            Change(
                id=r["id"],
                type=ChangeType(r["type"]),
                timestamp=datetime.fromisoformat(r["timestamp"]),
                repo_full_name=r["repo_full_name"],
                title=r["title"],
                url=r["url"],
                summary=r["summary"],
                metadata=json.loads(r["metadata"]) if r["metadata"] else {},
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # JSON export
    # ------------------------------------------------------------------

    def export_json(
        self,
        date: str,
        *,
        conversations: list[Conversation] | None = None,
        meetings: list[Meeting] | None = None,
        changes: list[Change] | None = None,
    ) -> Path:
        """Export activity data to a JSON file for the given date.

        Merges with any existing export file (additive by platform section).
        Returns the path to the JSON file.
        """
        exports_dir = EXPORTS_DIR
        exports_dir.mkdir(parents=True, exist_ok=True)
        export_path = exports_dir / f"{date}.json"
        tmp_path = export_path.with_suffix(".json.tmp")

        # Load existing export if present (for merging)
        existing: dict = {}
        if export_path.exists():
            try:
                existing = json.loads(export_path.read_text())
            except (json.JSONDecodeError, OSError):
                existing = {}

        now = datetime.now(UTC).isoformat()
        output = {
            "date": date,
            "exported_at": now,
        }

        # Webex section — merge conversations and meetings
        webex_section = existing.get("webex") or {}
        if conversations is not None:
            webex_section["fetched_at"] = now
            webex_section["conversations"] = [
                self._conversation_to_dict(c) for c in conversations
            ]
        if meetings is not None:
            webex_section["fetched_at"] = now
            webex_section["meetings"] = [self._meeting_to_dict(m) for m in meetings]
        if webex_section:
            output["webex"] = webex_section
        else:
            output["webex"] = existing.get("webex")

        # GitHub section
        github_section = existing.get("github") or {}
        if changes is not None:
            github_section = {
                "fetched_at": now,
                "changes": [self._change_to_dict(c) for c in changes],
            }
        if github_section:
            output["github"] = github_section
        else:
            output["github"] = existing.get("github")

        # Atomic write
        tmp_path.write_text(json.dumps(output, indent=2, default=str))
        os.replace(str(tmp_path), str(export_path))

        logger.info("Exported JSON for %s to %s", date, export_path)
        return export_path

    # ------------------------------------------------------------------
    # JSON serialization helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _user_to_dict(user: User) -> dict:
        """Convert a User to a dict."""
        return {"id": user.id, "display_name": user.display_name}

    @staticmethod
    def _thread_to_dict(thread: Thread | None) -> dict | None:
        """Convert a Thread to a dict."""
        if thread is None:
            return None
        return {
            "id": thread.id,
            "original_post_id": thread.original_post_id,
            "original_poster": {
                "id": thread.original_poster.id,
                "display_name": thread.original_poster.display_name,
            },
        }

    def _message_to_dict(self, msg: Message) -> dict:
        """Convert a Message to a dict."""
        return {
            "id": msg.id,
            "sender": self._user_to_dict(msg.sender),
            "timestamp": msg.timestamp.isoformat(),
            "content": msg.content,
            "thread": self._thread_to_dict(msg.thread),
        }

    def _conversation_to_dict(self, convo: Conversation) -> dict:
        """Convert a Conversation to a dict."""
        return {
            "id": convo.id,
            "space_id": convo.space_id,
            "space_type": convo.space_type.value,
            "is_threaded": convo.is_threaded,
            "start_time": convo.start_time.isoformat() if convo.start_time else None,
            "end_time": convo.end_time.isoformat() if convo.end_time else None,
            "duration_seconds": convo.duration_seconds,
            "participants": [self._user_to_dict(u) for u in convo.participants],
            "messages": [self._message_to_dict(m) for m in convo.messages],
        }

    def _meeting_to_dict(self, meeting: Meeting) -> dict:
        """Convert a Meeting to a dict."""
        summary = None
        if meeting.summary:
            summary = {
                "overview": meeting.summary.overview,
                "notes": meeting.summary.notes,
                "action_items": meeting.summary.action_items,
                "raw_json": meeting.summary.raw_json,
            }

        return {
            "id": meeting.id,
            "title": meeting.title,
            "start_time": meeting.start_time.isoformat(),
            "end_time": meeting.end_time.isoformat(),
            "duration_seconds": meeting.duration_seconds,
            "host": self._user_to_dict(meeting.host),
            "participants": [self._user_to_dict(p) for p in meeting.participants],
            "meeting_series_id": meeting.meeting_series_id,
            "site_url": meeting.site_url,
            "summary": summary,
            "transcript_snippets": [
                {
                    "speaker": self._user_to_dict(s.speaker),
                    "text": s.text,
                    "start_time": s.start_time.isoformat() if s.start_time else None,
                }
                for s in meeting.transcript_snippets
            ],
            "transcript_id": meeting.transcript_id,
            "transcript_vtt": meeting.transcript_vtt,
        }

    @staticmethod
    def _change_to_dict(change: Change) -> dict:
        """Convert a Change to a dict."""
        return {
            "id": change.id,
            "type": change.type.value,
            "timestamp": change.timestamp.isoformat(),
            "repo_full_name": change.repo_full_name,
            "title": change.title,
            "url": change.url,
            "summary": change.summary,
            "metadata": change.metadata,
        }

    # ------------------------------------------------------------------
    # Cache invalidation
    # ------------------------------------------------------------------

    def clear_date(self, date: str, platform: str | None = None) -> None:
        """Clear cached data for a date.

        If platform is specified, only clear that platform's data.
        Otherwise clear all data for the date.
        """
        cur = self._conn.cursor()
        try:
            cur.execute("BEGIN")

            if platform is None or platform == "webex":
                self._clear_webex_data(cur, date)
                self._clear_meeting_data(cur, date)
                cur.execute(
                    "DELETE FROM fetch_log WHERE date = ? AND platform = 'webex'",
                    (date,),
                )

            if platform is None or platform == "github":
                cur.execute("DELETE FROM changes WHERE date = ?", (date,))
                cur.execute(
                    "DELETE FROM fetch_log WHERE date = ? AND platform = 'github'",
                    (date,),
                )

            self._conn.commit()
            logger.info("Cleared %s data for %s", platform or "all", date)

        except Exception:
            self._conn.rollback()
            raise

    def _clear_webex_data(self, cur: sqlite3.Cursor, date: str) -> None:
        """Clear Webex conversation/message data for a date."""
        # Delete conversation_messages links
        cur.execute(
            """DELETE FROM conversation_messages
               WHERE conversation_id IN
                     (SELECT id FROM conversations WHERE date = ?)""",
            (date,),
        )
        # Delete conversation_participants
        cur.execute(
            """DELETE FROM conversation_participants
               WHERE conversation_id IN
                     (SELECT id FROM conversations WHERE date = ?)""",
            (date,),
        )
        # Delete message_recipients
        cur.execute(
            """DELETE FROM message_recipients
               WHERE message_id IN
                     (SELECT id FROM messages WHERE date = ?)""",
            (date,),
        )
        # Delete messages and conversations
        cur.execute("DELETE FROM messages WHERE date = ?", (date,))
        cur.execute("DELETE FROM conversations WHERE date = ?", (date,))

    def _clear_meeting_data(self, cur: sqlite3.Cursor, date: str) -> None:
        """Clear meeting data for a date."""
        cur.execute(
            """DELETE FROM transcript_snippets
               WHERE meeting_id IN
                     (SELECT id FROM meetings WHERE date = ?)""",
            (date,),
        )
        cur.execute(
            """DELETE FROM meeting_participants
               WHERE meeting_id IN
                     (SELECT id FROM meetings WHERE date = ?)""",
            (date,),
        )
        cur.execute("DELETE FROM meetings WHERE date = ?", (date,))

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
