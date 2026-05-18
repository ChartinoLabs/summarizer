"""Webex API interaction functions."""

import logging
from collections.abc import Generator
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, tzinfo

import requests
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn
from webexpythonsdk import WebexAPI
from webexpythonsdk.exceptions import ApiError
from webexpythonsdk.models.immutable import Message as SDKMessage, Person, Room

from summarizer.common.console_ui import console
from summarizer.common.models import (
    Meeting,
    MeetingSummary,
    Message,
    SpaceType,
    TranscriptSnippet,
    User,
)
from summarizer.webex.config import WebexConfig

logger = logging.getLogger(__name__)


def sdk_person_to_user(person: Person) -> User:
    """Convert a Webex API Person object to a User dataclass."""
    return User(id=person.id, display_name=person.displayName)


def get_space_type(room: Room) -> SpaceType:
    """Get the type of a space from a Webex API Room object."""
    if room.type == "direct":
        return SpaceType.DM
    elif room.type == "group":
        return SpaceType.GROUP
    else:
        raise ValueError(f"Unknown space type: {room.type}")


# Cache for person lookups to avoid repeated API calls for deleted users
_person_cache: dict[str, User] = {}


def safe_get_person(
    client: WebexAPI, person_id: str, cache: dict[str, User] | None = None
) -> User:
    """Safely fetch a person, returning a placeholder for deleted users.

    Single Responsibility: Handle all person-fetching errors in one place.

    Args:
        client: Webex API client
        person_id: ID of the person to fetch
        cache: Optional cache dictionary to store/retrieve users

    Returns:
        User object (real or placeholder for deleted users)
    """
    # Use provided cache or module-level cache
    cache = cache if cache is not None else _person_cache

    # Check cache first
    if person_id in cache:
        return cache[person_id]

    try:
        # Try to fetch the person from API
        sdk_person = client.people.get(person_id)
        user = sdk_person_to_user(sdk_person)
        cache[person_id] = user
        return user
    except ApiError as e:
        if "404" in str(e):
            # Person not found - create placeholder
            placeholder_user = User(id=person_id, display_name="[Deleted User]")
            cache[person_id] = placeholder_user
            logger.info(
                "Person %s no longer exists in Webex, using placeholder", person_id
            )
            return placeholder_user
        else:
            # Re-raise other API errors
            raise


@dataclass
class MessageAnalysisResult:
    """Result of analyzing messages for a specific date in a room."""

    room: Room
    messages: list[Message]
    last_activity: datetime | None
    had_activity_on_or_after_date: bool


class WebexClient:
    """Wrapper around Webex API client."""

    def __init__(self, config: WebexConfig, client: WebexAPI | None = None) -> None:
        """Initialize with configuration."""
        self.config = config

        if client:
            self._client = client
        else:
            # Get access token from OAuth or manual token
            access_token = config.get_access_token()
            if not access_token:
                raise ValueError(
                    "No valid Webex access token available. "
                    "Please authenticate with OAuth or provide a manual token."
                )

            logger.debug(
                f"Initializing Webex client with token (length: {len(access_token)})"
            )
            self._client = WebexAPI(access_token=access_token)

        self._me: Person | None = None

    @property
    def client(self) -> WebexAPI:
        """Get the underlying WebexAPI client."""
        return self._client

    def get_me(self) -> User:
        """Get user information as a User dataclass."""
        if not self._me:
            try:
                self._me = self._client.people.me()
            except ApiError as e:
                if e.response.status_code == 403:
                    # Try to provide helpful error message
                    if self.config.has_oauth_config():
                        # Try forcing a token refresh first
                        logger.debug("403 error with OAuth - attempting token refresh")
                        oauth_client = self.config.get_oauth_client()
                        if oauth_client:
                            try:
                                credentials = oauth_client.load_credentials()
                                if credentials:
                                    logger.debug(
                                        "Forcing token refresh due to 403 error"
                                    )
                                    refreshed = oauth_client.refresh_access_token(
                                        credentials
                                    )
                                    # Update the client with the refreshed token
                                    self._client = WebexAPI(
                                        access_token=refreshed.access_token
                                    )
                                    logger.debug(
                                        "Retrying API call with refreshed token"
                                    )
                                    # Retry the API call once
                                    self._me = self._client.people.me()
                                    return sdk_person_to_user(self._me)
                            except Exception as refresh_error:
                                logger.debug(f"Token refresh failed: {refresh_error}")

                        raise ValueError(
                            "Webex API access forbidden (403). "
                            "This usually means:\n"
                            "1. Your OAuth token has expired or is invalid\n"
                            "2. Your token is missing required scopes "
                            "(spark:messages_read, spark:rooms_read)\n"
                            "3. Your Webex account doesn't have the necessary "
                            "permissions\n\n"
                            "Try re-authenticating with: summarizer webex login"
                        ) from e
                    else:
                        raise ValueError(
                            "Webex API access forbidden (403). "
                            "This usually means:\n"
                            "1. Your access token has expired "
                            "(manual tokens expire every 12 hours)\n"
                            "2. Your token is missing required scopes\n"
                            "3. Your Webex account doesn't have the necessary "
                            "permissions\n\n"
                            "Get a new token from: "
                            "https://developer.webex.com/docs/getting-started\n"
                            "Or consider switching to OAuth authentication."
                        ) from e
                elif e.response.status_code == 401:
                    raise ValueError(
                        "Webex API authentication failed (401). "
                        "Your access token is invalid.\n"
                        "Please check your token and try again."
                    ) from e
                else:
                    raise ValueError(
                        f"Webex API error ({e.response.status_code}): {e}"
                    ) from e
        return sdk_person_to_user(self._me)

    def get_rooms_active_since_date(self, date: datetime) -> list[Room]:
        """Get all rooms that have had activity since the given date."""
        active_rooms: list[Room] = []
        seen_room_ids: set[str] = set()  # Track seen room IDs
        rooms = self._client.rooms.list(
            max=self.config.room_chunk_size, sortBy="lastactivity"
        )
        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Scanning rooms for activity..."),
            TextColumn("[green]Processed: {task.completed}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Scanning rooms for activity...", total=None)
            for room in rooms:
                logger.debug("Processing room: id=%s, title=%s", room.id, room.title)
                if room.id in seen_room_ids:
                    logger.debug(
                        "Room %s (ID %s) already processed, skipping...",
                        room.title,
                        room.id,
                    )
                    progress.update(task, advance=1)
                    continue
                seen_room_ids.add(room.id)
                if room.lastActivity is None:
                    progress.update(task, advance=1)
                    logger.debug(
                        "Room %s (ID %s) has no last activity date, skipping...",
                        room.title,
                        room.id,
                    )
                    continue
                if room.lastActivity.date() >= date.date():
                    logger.debug(
                        "Room %s (ID %s) has last activity at %s, which is on or "
                        "after date %s, adding to list...",
                        room.title,
                        room.id,
                        room.lastActivity,
                        date,
                    )
                    active_rooms.append(room)
                else:
                    # Still count the room as processed
                    progress.update(task, advance=1)
                    logger.debug(
                        "Room %s (ID %s) has last activity at %s, which is before "
                        "date %s, skipping...",
                        room.title,
                        room.id,
                        room.lastActivity,
                        date,
                    )
                    break
                progress.update(task, advance=1)
        logger.info("Total active rooms found: %d", len(active_rooms))
        return active_rooms

    def get_messages_for_rooms(
        self,
        rooms: list[Room],
        date: datetime,
        local_tz: tzinfo,
        all_messages_flag: bool = False,
    ) -> list[Message]:
        """Get all messages for the given rooms and date."""
        messages: list[Message] = []
        seen_message_ids: set[str] = set()  # Track seen message IDs

        # Compute the end-of-day boundary once for all rooms. Using before= tells
        # the Webex API to start pagination at the end of the target day rather than
        # at "now", eliminating months of backward pagination per room.
        # Pattern mirrors get_meetings_for_date() in this same file.
        day_start = datetime(date.year, date.month, date.day, tzinfo=local_tz)
        before_iso = (
            (day_start + timedelta(days=1))
            .astimezone(UTC)
            .strftime("%Y-%m-%dT%H:%M:%SZ")
        )

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Fetching messages from active rooms..."),
            TextColumn("[green]Processed: {task.completed}/{task.total}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task(
                "Fetching messages from rooms...", total=len(rooms)
            )
            logger.info("Fetching messages from %d active rooms", len(rooms))
            with ThreadPoolExecutor(max_workers=10) as executor:
                futures = {
                    executor.submit(
                        get_messages,
                        self._client,
                        date,
                        self.config.user_email,
                        room,
                        local_tz,
                        all_messages_flag,
                        before_iso,
                    ): room
                    for room in rooms
                }
                for future in as_completed(futures):
                    result: MessageAnalysisResult = future.result()
                    if result.messages:
                        for msg in result.messages:
                            # Only add if we haven't seen this message ID before
                            if msg.id not in seen_message_ids:
                                seen_message_ids.add(msg.id)
                                logger.debug(
                                    (
                                        "Message ID %s in room %s (ID %s) from sender "
                                        "%s at %s"
                                    ),
                                    msg.id,
                                    result.room.title,
                                    result.room.id,
                                    msg.sender.display_name,
                                    msg.timestamp,
                                )
                                messages.append(msg)
                            else:
                                logger.debug(
                                    "Skipping duplicate message ID %s",
                                    msg.id,
                                )
                    progress.update(task, advance=1)

        logger.info(f"Total messages aggregated: {len(messages)}")
        messages.sort(key=lambda x: x.timestamp)
        return messages

    def find_room_by_id(self, room_id: str) -> Room | None:
        """Find a room by exact room ID match.

        Args:
            room_id: The exact room ID to find

        Returns:
            Room object if found, None otherwise
        """
        try:
            return self._client.rooms.get(roomId=room_id)
        except ApiError as e:
            if "404" in str(e):
                logger.info("Room with ID %s not found", room_id)
                return None
            else:
                raise

    def find_room_by_name(self, room_name: str) -> Room | None:
        """Find a room by exact room name match.

        Args:
            room_name: The exact room name to find

        Returns:
            Room object if found, None otherwise
        """
        rooms = self._client.rooms.list(max=1000)  # Get more rooms for searching
        for room in rooms:
            if room.title == room_name:
                logger.info("Found room '%s' with ID %s", room_name, room.id)
                return room
        logger.info("No room found with exact name '%s'", room_name)
        return None

    def find_dm_room_by_person_name(self, person_name: str) -> Room | None:
        """Find a direct message room with a specific person by exact name match.

        Args:
            person_name: The exact display name of the person to find DM with

        Returns:
            Room object if found, None otherwise
        """
        # Get all rooms and filter for direct message rooms
        all_rooms = self._client.rooms.list(max=1000)
        dm_rooms = [room for room in all_rooms if room.type == "direct"]

        for room in dm_rooms:
            try:
                # Get memberships to find the other person in the DM
                memberships = self._client.memberships.list(roomId=room.id)
                me = self.get_me()

                for membership in memberships:
                    if membership.personId != me.id:
                        # This is the other person in the DM
                        other_person = safe_get_person(
                            self._client, membership.personId
                        )
                        if other_person.display_name == person_name:
                            logger.info(
                                "Found DM room with %s (ID: %s, Room ID: %s)",
                                person_name,
                                membership.personId,
                                room.id,
                            )
                            return room
            except ApiError as e:
                logger.warning("Error checking memberships for room %s: %s", room.id, e)
                continue

        logger.info("No DM room found with person named '%s'", person_name)
        return None

    def get_all_messages_from_room(
        self, room: Room, max_messages: int = 1000, local_tz: tzinfo | None = None
    ) -> list[Message]:
        """Get all messages from a specific room up to max_messages limit.

        Args:
            room: The room to retrieve messages from
            max_messages: Maximum number of messages to retrieve
            local_tz: Local timezone for timestamp conversion

        Returns:
            List of Message objects sorted chronologically
        """
        if local_tz is None:
            local_tz = UTC

        messages: list[Message] = []
        sdk_messages = self._client.messages.list(roomId=room.id, max=max_messages)

        logger.info(
            "Retrieving up to %d messages from room '%s'", max_messages, room.title
        )

        with Progress(
            SpinnerColumn(),
            TextColumn(f"[bold blue]Fetching messages from {room.title}..."),
            TextColumn("[green]Retrieved: {task.completed}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Fetching messages...", total=None)

            for sdk_message in sdk_messages:
                if len(messages) >= max_messages:
                    break

                if sdk_message.created is None:
                    logger.warning(
                        "Message %s has no creation date, skipping...", sdk_message.id
                    )
                    continue

                msg = create_message(sdk_message, self._client, room, local_tz)
                messages.append(msg)
                progress.update(task, advance=1)

        logger.info("Retrieved %d messages from room '%s'", len(messages), room.title)
        # Sort chronologically (oldest first)
        messages.sort(key=lambda x: x.timestamp)
        return messages

    def get_activity(
        self,
        date: datetime,
        local_tz: tzinfo,
        room_chunk_size: int = 50,
        all_messages_flag: bool = False,
    ) -> list[Message]:
        """Get all activity for the specified date as a list of Message objects."""
        active_rooms = self.get_rooms_active_since_date(date)
        logger.info(
            "A total of %d active rooms were found on date %s", len(active_rooms), date
        )
        messages = self.get_messages_for_rooms(
            active_rooms, date, local_tz, all_messages_flag
        )
        logger.info("A total of %d messages were found on date %s", len(messages), date)
        messages.sort(key=lambda x: x.timestamp)
        return messages

    # =========================================
    # Meeting / Transcript / Summary methods
    # =========================================

    _WEBEX_API_BASE = "https://webexapis.com/v1"

    def _webex_api_get(
        self,
        endpoint: str,
        params: dict[str, str] | None = None,
    ) -> dict | list | None:
        """Authenticated GET to the Webex REST API.

        Returns the parsed JSON body on success, or None on 401/403/404.

        Args:
            endpoint: API path relative to base URL (e.g. "/meetingTranscripts")
            params: Optional query parameters

        Returns:
            Parsed JSON response or None on expected error codes
        """
        token = self.config.get_access_token()
        if not token:
            logger.warning("No access token available for REST call to %s", endpoint)
            return None

        url = f"{self._WEBEX_API_BASE}{endpoint}"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=30)
            resp.raise_for_status()
            return resp.json()
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status in (401, 403, 404):
                logger.debug(
                    "REST %s returned %s for %s — returning None",
                    endpoint,
                    status,
                    params,
                )
                return None
            logger.warning("REST %s failed (%s): %s", endpoint, status, exc)
            return None
        except requests.exceptions.RequestException as exc:
            logger.warning("REST request to %s failed: %s", endpoint, exc)
            return None

    def _webex_api_get_text(
        self,
        endpoint: str,
        params: dict[str, str] | None = None,
    ) -> str | None:
        """Authenticated GET returning raw text (e.g. VTT transcript downloads).

        Args:
            endpoint: API path relative to base URL
            params: Optional query parameters

        Returns:
            Response body as text, or None on error
        """
        token = self.config.get_access_token()
        if not token:
            logger.warning("No access token available for text GET %s", endpoint)
            return None

        url = f"{self._WEBEX_API_BASE}{endpoint}"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            resp = requests.get(url, headers=headers, params=params, timeout=60)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.HTTPError as exc:
            status = exc.response.status_code if exc.response is not None else 0
            if status in (401, 403, 404):
                logger.debug(
                    "Text GET %s returned %s — returning None", endpoint, status
                )
                return None
            logger.warning("Text GET %s failed (%s): %s", endpoint, status, exc)
            return None
        except requests.exceptions.RequestException as exc:
            logger.warning("Text GET request to %s failed: %s", endpoint, exc)
            return None

    def get_meetings_for_date(self, date: datetime, local_tz: tzinfo) -> list[Meeting]:
        """Fetch meetings from the Webex Meetings API for the target date.

        Uses the SDK ``meetings.list()`` method to retrieve scheduled meetings
        that fall within the target date (in local timezone).

        Args:
            date: Target date to query
            local_tz: User's local timezone for date boundary calculation

        Returns:
            List of Meeting dataclasses (metadata only, no transcripts/summaries)
        """
        # Build date boundaries in local tz, then convert to UTC ISO strings
        day_start = datetime(date.year, date.month, date.day, tzinfo=local_tz)
        day_end = day_start + timedelta(days=1)
        from_str = day_start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        to_str = day_end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        # NOTE: Webex's `/v1/meetings?meetingType=meeting` endpoint silently
        # ignores the `from`/`to` query params (documented behavior — those are
        # only honored for meetingType=scheduledMeeting). Empirically the
        # endpoint still needs them present to return any past-meeting window
        # at all; without them the response is empty. We therefore still send
        # them, but filter client-side by actual start_time to scope to the
        # target local day.
        meetings: list[Meeting] = []
        skipped_out_of_window = 0
        try:
            sdk_meetings = self._client.meetings.list(
                meetingType="meeting", **{"from": from_str, "to": to_str}
            )
            for m in sdk_meetings:
                start_dt = datetime.fromisoformat(m.start).astimezone(local_tz)
                # Drop meetings that don't actually start within the target day
                if not (day_start <= start_dt < day_end):
                    skipped_out_of_window += 1
                    logger.debug(
                        "Skipping meeting '%s' (id=%s) — start %s outside "
                        "target window %s to %s",
                        getattr(m, "title", "(Untitled)"),
                        getattr(m, "id", ""),
                        start_dt.isoformat(),
                        day_start.isoformat(),
                        day_end.isoformat(),
                    )
                    continue
                end_dt = datetime.fromisoformat(m.end).astimezone(local_tz)
                duration = int((end_dt - start_dt).total_seconds())
                host = User(
                    id=getattr(m, "hostUserId", "") or "",
                    display_name=getattr(m, "hostDisplayName", "") or "",
                )
                meetings.append(
                    Meeting(
                        id=m.id,
                        title=m.title or "(Untitled Meeting)",
                        start_time=start_dt,
                        end_time=end_dt,
                        duration_seconds=duration,
                        host=host,
                        meeting_series_id=getattr(m, "meetingSeriesId", None),
                        site_url=getattr(m, "siteUrl", None),
                    )
                )
        except ApiError as exc:
            logger.warning("Failed to list meetings: %s", exc)
        except Exception as exc:
            logger.warning("Unexpected error listing meetings: %s", exc)

        logger.info(
            "Found %d meetings for %s (%d returned by API were outside window)",
            len(meetings), date.date(), skipped_out_of_window,
        )
        return meetings

    def get_meeting_transcripts_for_date(
        self, date: datetime, local_tz: tzinfo
    ) -> dict[str, str]:
        """Get a mapping of meetingId → transcriptId for transcripts on the date.

        Args:
            date: Target date
            local_tz: User's local timezone

        Returns:
            Dict mapping meeting ID to its transcript ID
        """
        day_start = datetime(date.year, date.month, date.day, tzinfo=local_tz)
        day_end = day_start + timedelta(days=1)
        from_str = day_start.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        to_str = day_end.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        data = self._webex_api_get(
            "/meetingTranscripts",
            params={"meetingStartTimeFrom": from_str, "meetingStartTimeTo": to_str},
        )
        if not data or "items" not in data:
            return {}

        mapping: dict[str, str] = {}
        for item in data["items"]:
            meeting_id = item.get("meetingId")
            transcript_id = item.get("id")
            if meeting_id and transcript_id:
                mapping[meeting_id] = transcript_id

        logger.info("Found %d transcript(s) for %s", len(mapping), date.date())
        return mapping

    def get_transcript_snippets(self, transcript_id: str) -> list[TranscriptSnippet]:
        """Fetch all speaker-attributed transcript snippets for a transcript.

        Paginates through all pages to return the complete set of snippets.

        Args:
            transcript_id: The transcript ID to fetch snippets for

        Returns:
            List of TranscriptSnippet dataclasses
        """
        snippets: list[TranscriptSnippet] = []
        endpoint = f"/meetingTranscripts/{transcript_id}/snippets"

        while endpoint:
            data = self._webex_api_get(endpoint)
            if not data or "items" not in data:
                break

            for item in data["items"]:
                speaker = User(
                    id=item.get("personId", ""),
                    display_name=item.get("personName", "Unknown Speaker"),
                )
                start_time = None
                if item.get("startTime"):
                    try:
                        start_time = datetime.fromisoformat(item["startTime"])
                    except (ValueError, TypeError):
                        pass
                snippets.append(
                    TranscriptSnippet(
                        speaker=speaker,
                        text=item.get("text", ""),
                        start_time=start_time,
                    )
                )

            # Follow pagination link if present
            next_url = data.get("next")
            if next_url and isinstance(next_url, str):
                # next_url is a full URL; strip the base to get the endpoint
                if next_url.startswith(self._WEBEX_API_BASE):
                    endpoint = next_url[len(self._WEBEX_API_BASE) :]
                else:
                    endpoint = next_url
            else:
                endpoint = None  # type: ignore[assignment]

        return snippets

    def download_transcript_vtt(self, transcript_id: str) -> str | None:
        """Download the full WebVTT transcript for a meeting.

        Args:
            transcript_id: The transcript ID to download

        Returns:
            WebVTT content as a string, or None if unavailable
        """
        return self._webex_api_get_text(f"/meetingTranscripts/{transcript_id}/download")

    def get_meeting_summary(self, meeting_id: str) -> MeetingSummary | None:
        """Fetch the AI-generated summary for a specific meeting.

        Args:
            meeting_id: The meeting ID to fetch the summary for

        Returns:
            MeetingSummary dataclass or None if unavailable
        """
        data = self._webex_api_get(
            "/meetingSummaries", params={"meetingId": meeting_id}
        )
        if not data or "items" not in data or not data["items"]:
            return None

        item = data["items"][0]
        return MeetingSummary(
            overview=item.get("overview", ""),
            notes=item.get("notes", []),
            action_items=item.get("actionItems", []),
            raw_json=item,
        )

    def get_meeting_participants(self, meeting_id: str) -> list[User]:
        """Fetch participants for a specific meeting.

        Uses the ``GET /meetingParticipants`` endpoint to retrieve the list
        of people who actually joined the meeting.

        Args:
            meeting_id: The meeting ID to fetch participants for

        Returns:
            List of User dataclasses for each participant
        """
        data = self._webex_api_get(
            "/meetingParticipants", params={"meetingId": meeting_id}
        )
        if not data or "items" not in data:
            return []

        participants: list[User] = []
        for item in data["items"]:
            user_id = item.get("id", "") or ""
            display_name = item.get("displayName", "") or ""
            if not display_name:
                # Fall back to email if display name missing
                display_name = item.get("email", "Unknown")
            participants.append(User(id=user_id, display_name=display_name))

        return participants

    def get_meetings_with_details(
        self, date: datetime, local_tz: tzinfo
    ) -> list[Meeting]:
        """Fetch meetings and enrich each with transcript snippets and AI summary.

        Orchestrator method that calls the individual meeting, transcript, and
        summary methods, then merges results into fully-enriched Meeting objects.

        Args:
            date: Target date
            local_tz: User's local timezone

        Returns:
            List of Meeting dataclasses enriched with summaries and transcripts
        """
        meetings = self.get_meetings_for_date(date, local_tz)
        if not meetings:
            return meetings

        # Get transcript mapping for the date
        transcript_map = self.get_meeting_transcripts_for_date(date, local_tz)

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Enriching meetings with details..."),
            TextColumn("[green]{task.completed}/{task.total}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Enriching meetings...", total=len(meetings))

            for meeting in meetings:
                # Attach transcript if available
                t_id = transcript_map.get(meeting.id)
                if t_id:
                    meeting.transcript_id = t_id
                    try:
                        meeting.transcript_snippets = self.get_transcript_snippets(t_id)
                    except Exception as exc:
                        logger.warning(
                            "Failed to get transcript snippets for %s: %s",
                            meeting.id,
                            exc,
                        )
                    try:
                        meeting.transcript_vtt = self.download_transcript_vtt(t_id)
                    except Exception as exc:
                        logger.warning(
                            "Failed to download VTT transcript for %s: %s",
                            meeting.id,
                            exc,
                        )

                # Attach AI summary
                try:
                    meeting.summary = self.get_meeting_summary(meeting.id)
                except Exception as exc:
                    logger.warning(
                        "Failed to get meeting summary for %s: %s",
                        meeting.id,
                        exc,
                    )

                # Attach participants
                try:
                    meeting.participants = self.get_meeting_participants(meeting.id)
                except Exception as exc:
                    logger.warning(
                        "Failed to get participants for %s: %s",
                        meeting.id,
                        exc,
                    )

                progress.update(task, advance=1)

        enriched_count = sum(1 for m in meetings if m.summary or m.transcript_snippets)
        logger.info(
            "Enriched %d/%d meetings with summaries/transcripts",
            enriched_count,
            len(meetings),
        )
        return meetings

    def add_users_to_room(
        self, room_id: str, user_emails: list[str]
    ) -> tuple[list[str], list[tuple[str, str]]]:
        """Add multiple users to a Webex room.

        This method iterates through a list of user email addresses and attempts to
        add each user to the specified room via the Webex memberships API. Users who
        are already members are counted as successful additions. All API errors are
        caught and reported.

        Args:
            room_id: The unique identifier of the room to add users to
            user_emails: List of email addresses to add to the room

        Returns:
            A tuple containing:
                - List of successfully added email addresses
                - List of tuples (email, error_message) for failed additions

        Raises:
            ApiError: Only if the room itself cannot be found or accessed
        """
        successful: list[str] = []
        failed: list[tuple[str, str]] = []

        # Verify room exists first
        try:
            room = self._client.rooms.get(roomId=room_id)
            logger.info("Adding users to room '%s' (ID: %s)", room.title, room_id)
        except ApiError as e:
            if "404" in str(e):
                logger.error("Room with ID %s not found", room_id)
                raise
            else:
                logger.error("Error accessing room %s: %s", room_id, e)
                raise

        with Progress(
            SpinnerColumn(),
            TextColumn("[bold blue]Adding users to room..."),
            TextColumn("[green]Processed: {task.completed}/{task.total}"),
            BarColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("Adding users...", total=len(user_emails))

            for email in user_emails:
                try:
                    # Attempt to add user to room
                    self._client.memberships.create(roomId=room_id, personEmail=email)
                    logger.debug("Successfully added %s to room %s", email, room_id)
                    successful.append(email)
                except ApiError as e:
                    error_msg = str(e)
                    # If user is already a member, count as success
                    if "409" in error_msg or "already" in error_msg.lower():
                        logger.debug(
                            "User %s is already a member of room %s", email, room_id
                        )
                        successful.append(email)
                    else:
                        # Log and track other errors
                        logger.warning(
                            "Failed to add %s to room %s: %s", email, room_id, e
                        )
                        failed.append((email, error_msg))
                except Exception as e:
                    # Catch any non-API errors
                    error_msg = f"Unexpected error: {e}"
                    logger.error(
                        "Unexpected error adding %s to room %s: %s", email, room_id, e
                    )
                    failed.append((email, error_msg))

                progress.update(task, advance=1)

        logger.info(
            "User addition complete: %d successful, %d failed",
            len(successful),
            len(failed),
        )
        return successful, failed


def parse_message_time(sdk_message: SDKMessage, local_tz: tzinfo) -> datetime:
    """Parse the message creation time to local timezone."""
    message_time = datetime.strptime(str(sdk_message.created), "%Y-%m-%dT%H:%M:%S.%fZ")
    message_time = message_time.replace(tzinfo=UTC).astimezone(local_tz)
    return message_time


def create_message(
    sdk_message: SDKMessage, client: WebexAPI, room: Room, local_tz: tzinfo
) -> Message:
    """Create a Message object from an SDKMessage."""
    sender = safe_get_person(client, sdk_message.personId)
    recipients: list[User] = []  # Not available from SDK directly
    message_time = parse_message_time(sdk_message, local_tz)
    return Message(
        id=sdk_message.id,
        space_id=room.id,
        space_type=get_space_type(room),
        space_name=room.title,
        sender=sender,
        recipients=recipients,
        timestamp=message_time,
        content=sdk_message.text or "",
    )


def build_analysis_result(
    room: Room,
    all_messages: list[Message],
    last_activity: datetime | None,
    had_activity_on_or_after_date: bool,
    user_sent: bool,
    all_messages_flag: bool = False,
) -> MessageAnalysisResult:
    """Build the MessageAnalysisResult based on whether the user sent a message."""
    if user_sent or all_messages_flag:
        return MessageAnalysisResult(
            room=room,
            messages=all_messages,
            last_activity=last_activity,
            had_activity_on_or_after_date=had_activity_on_or_after_date,
        )
    else:
        return MessageAnalysisResult(
            room=room,
            messages=[],
            last_activity=last_activity,
            had_activity_on_or_after_date=had_activity_on_or_after_date,
        )


def get_messages(
    client: WebexAPI,
    date: datetime,
    user_email: str,
    room: Room,
    local_tz: tzinfo,
    all_messages_flag: bool = False,
    before: str | None = None,
) -> MessageAnalysisResult:
    """Get all messages for a specific date in a room.

    Only returns messages if the user sent at least one message in that room on that
    date, unless all_messages_flag is True which returns all messages regardless.

    Args:
        before: ISO8601 UTC timestamp (e.g. "2025-09-02T04:00:00Z"). When provided,
                pagination starts at this point rather than at the current time,
                eliminating months of backward pagination for historical dates.
    """
    all_messages: list[Message] = []
    user_sent = False
    had_activity_on_or_after_date = False

    messages: Generator[SDKMessage, None, None] = client.messages.list(
        roomId=room.id, before=before
    )
    last_activity: datetime | None = None

    for sdk_message in messages:
        if sdk_message.created is None:
            logger.warning(
                "Message %s has no creation date, skipping...", sdk_message.id
            )
            continue

        message_time = parse_message_time(sdk_message, local_tz)
        if last_activity is None or message_time > last_activity:
            last_activity = message_time

        if message_time.date() == date.date():
            msg = create_message(sdk_message, client, room, local_tz)
            logger.debug(
                "Processing SDK message %s from email %s created at %s",
                sdk_message.id,
                sdk_message.personEmail,
                sdk_message.created,
            )
            all_messages.append(msg)
            if sdk_message.personEmail == user_email:
                logger.debug(
                    "Authenticated user (%s == %s) sent message %s",
                    sdk_message.personEmail,
                    user_email,
                    sdk_message.id,
                )
                user_sent = True

        if message_time.date() >= date.date():
            had_activity_on_or_after_date = True
        elif message_time.date() < date.date():
            logger.debug(
                "Message %s from email %s is before the target date %s, "
                "stopping processing...",
                sdk_message.id,
                sdk_message.personEmail,
                date,
            )
            break

    return build_analysis_result(
        room,
        all_messages,
        last_activity,
        had_activity_on_or_after_date,
        user_sent,
        all_messages_flag,
    )
