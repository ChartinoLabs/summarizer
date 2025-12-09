"""Webex Meetings API interaction functions."""

import logging
from collections.abc import Generator
from datetime import datetime, time, timedelta, tzinfo
from zoneinfo import ZoneInfo

import requests
from pydantic import BaseModel, Field, computed_field
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class Meeting(BaseModel):
    """Represents a Webex meeting.

    This model represents all fields returned from the WebEx Meetings API with
    additional computed properties and methods for handling multi-day meetings.

    Attributes:
        id: Unique identifier for the meeting.
        meeting_series_id: Identifier for the recurring meeting series.
        title: Title of the meeting.
        start: Start time of the meeting in ISO 8601 format.
        end: End time of the meeting in ISO 8601 format.
        timezone: Timezone of the meeting (e.g., 'America/New_York').
        state: Current state (e.g., 'active', 'scheduled', 'ended', 'cancelled').
        meeting_type: Type of meeting (e.g., 'meeting', 'scheduledMeeting').
        is_recurring: Whether the meeting is part of a recurring series.
        host_email: Email address of the meeting host.
        host_display_name: Display name of the meeting host.
        web_link: URL to join the meeting via web browser.
        sip_address: SIP address for joining via SIP clients.
        meeting_number: Meeting access number.
    """

    id: str
    meeting_series_id: str | None = Field(None, alias="meetingSeriesId")
    title: str
    start: str
    end: str
    timezone: str
    state: str = Field(default="scheduled")
    meeting_type: str = Field(alias="meetingType", default="meeting")
    is_recurring: bool = Field(alias="isRecurring", default=False)
    host_email: str | None = Field(None, alias="hostEmail")
    host_display_name: str | None = Field(None, alias="hostDisplayName")
    web_link: str = Field(alias="webLink", default="")
    sip_address: str | None = Field(None, alias="sipAddress")
    meeting_number: str | None = Field(None, alias="meetingNumber")

    class Config:
        """Pydantic configuration."""

        populate_by_name = True

    @computed_field
    @property
    def duration_minutes(self) -> float:
        """Calculate meeting duration in minutes.

        Returns:
            Duration in minutes as a float.

        Raises:
            ValueError: If start or end times cannot be parsed.
        """
        try:
            start_dt = datetime.fromisoformat(self.start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(self.end.replace("Z", "+00:00"))
            delta = end_dt - start_dt
            return delta.total_seconds() / 60
        except (ValueError, AttributeError) as e:
            logger.error(
                "Failed to calculate duration for meeting %s: %s", self.id, str(e)
            )
            raise ValueError(f"Invalid meeting time format: {e}") from e

    @computed_field
    @property
    def is_scheduled(self) -> bool:
        """Check if the meeting is in scheduled state.

        Returns:
            True if state is 'scheduled', False otherwise.
        """
        return self.state == "scheduled"

    def spans_multiple_days(self) -> bool:
        """Check if the meeting spans multiple calendar days.

        This method checks if the meeting crosses midnight boundaries in the
        meeting's local timezone.

        Returns:
            True if the meeting spans multiple days, False otherwise.
        """
        try:
            # Parse meeting timezone
            meeting_tz: tzinfo = ZoneInfo(self.timezone)

            # Parse start and end times
            start_dt = datetime.fromisoformat(self.start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(self.end.replace("Z", "+00:00"))

            # Convert to meeting's local timezone
            start_local = start_dt.astimezone(meeting_tz)
            end_local = end_dt.astimezone(meeting_tz)

            # Compare dates
            return start_local.date() != end_local.date()

        except Exception as e:
            logger.warning(
                "Failed to check multi-day span for meeting %s: %s", self.id, str(e)
            )
            return False

    def split_by_day(self) -> list["Meeting"]:
        """Split a multi-day meeting into single-day segments.

        For meetings that span multiple days (F-WEBEX-17), this method creates
        separate Meeting objects for each calendar day, with start/end times
        adjusted to midnight boundaries.

        Returns:
            List of Meeting objects, one per day. If the meeting doesn't span
            multiple days, returns a list containing just this meeting.

        Example:
            A meeting from Wed 23:00 to Fri 02:00 would be split into:
            - Wed 23:00 to Wed 23:59:59
            - Thu 00:00 to Thu 23:59:59
            - Fri 00:00 to Fri 02:00
        """
        if not self.spans_multiple_days():
            return [self]

        try:
            # Parse meeting timezone
            meeting_tz: tzinfo = ZoneInfo(self.timezone)

            # Parse start and end times
            start_dt = datetime.fromisoformat(self.start.replace("Z", "+00:00"))
            end_dt = datetime.fromisoformat(self.end.replace("Z", "+00:00"))

            # Convert to meeting's local timezone
            start_local = start_dt.astimezone(meeting_tz)
            end_local = end_dt.astimezone(meeting_tz)

            # Create segments for each day
            segments: list[Meeting] = []
            current_start = start_local

            while current_start.date() < end_local.date():
                # End of current day
                current_end = datetime.combine(
                    current_start.date(), time.max, tzinfo=meeting_tz
                )

                # Create segment for this day
                segment = self.model_copy(
                    update={
                        "start": current_start.isoformat(),
                        "end": current_end.isoformat(),
                    }
                )
                segments.append(segment)

                # Move to next day
                next_date = current_start.date() + timedelta(days=1)
                current_start = datetime.combine(
                    next_date, time.min, tzinfo=meeting_tz
                )

            # Final segment (last partial day)
            final_segment = self.model_copy(
                update={
                    "start": current_start.isoformat(),
                    "end": end_local.isoformat(),
                }
            )
            segments.append(final_segment)

            return segments

        except Exception as e:
            logger.error(
                "Failed to split multi-day meeting %s: %s", self.id, str(e)
            )
            # Return original meeting if splitting fails
            return [self]


class MeetingsListResponse(BaseModel):
    """Response from the Webex meetings list API.

    Attributes:
        items: List of meetings returned by the API.
    """

    items: list[Meeting] = Field(default_factory=list)


def calculate_business_week_range(
    target_date: datetime,
) -> tuple[datetime, datetime]:
    """Calculate start and end of business week for a target date.

    The business week is defined as Monday through Friday. This function returns
    the start of Monday (00:00:00) and end of Friday (23:59:59) for the week
    containing the target date.

    Args:
        target_date: The date to calculate the business week for.

    Returns:
        A tuple of (week_start, week_end) where:
            - week_start: Start of Monday at 00:00:00
            - week_end: End of Friday at 23:59:59
    """
    # Get the day of week (0 = Monday, 6 = Sunday)
    day_of_week = target_date.weekday()

    # Calculate days to subtract to get to Monday
    days_to_monday = day_of_week

    # Calculate start of Monday
    week_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = week_start - timedelta(days=days_to_monday)

    # Calculate end of Friday (4 days after Monday)
    week_end = week_start + timedelta(days=4)
    week_end = week_end.replace(hour=23, minute=59, second=59, microsecond=999999)

    return week_start, week_end


def is_meeting_on_date(meeting: Meeting, target_date: datetime) -> bool:
    """Check if a meeting occurs on or spans across the target date.

    This function handles multi-day meetings by checking if the target date
    falls within the meeting's start and end time range. It properly accounts
    for timezone conversions.

    Args:
        meeting: The meeting to check.
        target_date: The date to check against.

    Returns:
        True if the meeting occurs on or spans the target date, False otherwise.
    """
    try:
        # Parse meeting timezone
        meeting_tz: tzinfo = ZoneInfo(meeting.timezone)

        # Parse meeting start and end times
        meeting_start = datetime.fromisoformat(meeting.start.replace("Z", "+00:00"))
        meeting_end = datetime.fromisoformat(meeting.end.replace("Z", "+00:00"))

        # Convert to meeting's local timezone
        meeting_start_local = meeting_start.astimezone(meeting_tz)
        meeting_end_local = meeting_end.astimezone(meeting_tz)

        # Convert target_date to meeting's timezone
        target_date_tz = target_date.astimezone(meeting_tz)

        # Get date boundaries for target date in meeting's timezone
        target_date_start = datetime.combine(
            target_date_tz.date(), time.min, tzinfo=meeting_tz
        )
        target_date_end = datetime.combine(
            target_date_tz.date(), time.max, tzinfo=meeting_tz
        )

        # Check if meeting overlaps with target date
        # Meeting overlaps if it starts before the day ends AND ends after the
        # day starts
        overlaps = (
            meeting_start_local <= target_date_end
            and meeting_end_local >= target_date_start
        )

        return overlaps

    except Exception as e:
        logger.warning(
            "Failed to parse meeting times for meeting %s: %s",
            meeting.id,
            e,
        )
        return False


class MeetingsClient:
    """Client for interacting with Webex Meetings API.

    This client provides methods to retrieve and filter meetings from the Webex
    Meetings API. It includes retry logic for resilient API interactions,
    proper pagination support, and business week filtering capabilities.

    The client implements exponential backoff for rate limit errors (429) and
    handles multi-day meeting scenarios per F-WEBEX-17 requirements.

    Attributes:
        access_token: WebEx API Bearer token for authentication.
        session: Requests session for API calls with configured headers.
    """

    # API Configuration Constants
    BASE_URL = "https://webexapis.com/v1"
    DEFAULT_TIMEOUT = 10  # seconds
    MAX_RETRIES = 3

    def __init__(self, access_token: str) -> None:
        """Initialize the Meetings client.

        Args:
            access_token: Valid WebEx API access token.

        Raises:
            ValueError: If access_token is empty or None.
        """
        if not access_token:
            raise ValueError("Access token is required for MeetingsClient")

        self.access_token = access_token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
            }
        )

    @retry(
        retry=retry_if_exception_type((requests.exceptions.RequestException,)),
        stop=stop_after_attempt(MAX_RETRIES),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    def _make_request(
        self, method: str, endpoint: str, **kwargs: dict[str, str]
    ) -> requests.Response:
        """Make an HTTP request with retry logic and exponential backoff.

        This method wraps requests with retry logic using tenacity. It automatically
        retries on transient network errors and rate limit responses (429) with
        exponential backoff as per the architect's design requirements.

        The retry strategy implements:
        1. Exponential backoff with 2-10 second wait times
        2. Maximum of 3 retry attempts (MAX_RETRIES)
        3. Automatic retry on 429 (rate limit) responses
        4. 10-second timeout on all requests (DEFAULT_TIMEOUT)

        Args:
            method: HTTP method (GET, POST, etc.).
            endpoint: API endpoint path (without base URL).
            **kwargs: Additional keyword arguments to pass to requests.

        Returns:
            Response object from the successful request.

        Raises:
            requests.exceptions.HTTPError: If request fails with non-retryable status.
            requests.exceptions.RequestException: If request fails after all retries.
            requests.exceptions.Timeout: If request exceeds timeout threshold.
        """
        url = f"{self.BASE_URL}/{endpoint}"

        # Set timeout if not provided
        if "timeout" not in kwargs:
            kwargs["timeout"] = self.DEFAULT_TIMEOUT

        logger.debug("Making %s request to %s", method, url)

        response = self.session.request(method, url, **kwargs)

        # Check for rate limiting - raise exception to trigger retry
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After", "unknown")
            logger.warning(
                "Rate limit hit (429). Retry-After: %s. Will retry with backoff.",
                retry_after
            )
            response.raise_for_status()  # This will raise and trigger tenacity retry

        # Raise for other HTTP errors
        response.raise_for_status()

        return response

    def list_meetings(
        self,
        from_date: datetime | None = None,
        to_date: datetime | None = None,
        max_results: int = 100,
    ) -> Generator[Meeting, None, None]:
        """List meetings with optional date filtering and pagination support.

        This method retrieves meetings from the Webex Meetings API with automatic
        pagination. It yields meetings one at a time, handling pagination
        transparently.

        Args:
            from_date: Start date for meeting search (inclusive).
            to_date: End date for meeting search (inclusive).
            max_results: Maximum number of meetings to retrieve per page (max 100).

        Yields:
            Meeting objects matching the search criteria.

        Raises:
            requests.exceptions.RequestException: If API request fails after retries.
        """
        params: dict[str, str | int] = {"max": min(max_results, 100)}

        if from_date:
            params["from"] = from_date.isoformat()
        if to_date:
            params["to"] = to_date.isoformat()

        endpoint = "meetings"
        has_more = True

        while has_more:
            response = self._make_request("GET", endpoint, params=params)
            data = response.json()

            # Parse response
            meetings_response = MeetingsListResponse(**data)

            # Yield each meeting
            yield from meetings_response.items

            # Check for pagination
            links = response.links
            has_more = "next" in links

            if has_more:
                # Extract the next URL and update params with cursor
                next_url = links["next"]["url"]
                # The next URL contains all params including cursor
                # We need to extract just the params
                if "?" in next_url:
                    query_string = next_url.split("?", 1)[1]
                    # Parse query string and update params
                    new_params = {}
                    for param in query_string.split("&"):
                        if "=" in param:
                            key, value = param.split("=", 1)
                            new_params[key] = value
                    params = new_params
                else:
                    has_more = False

    def get_meetings_for_date(
        self,
        target_date: datetime,
        include_cancelled: bool = False,
    ) -> list[Meeting]:
        """Get all meetings for a specific date.

        This method retrieves meetings for a target date, properly handling:
        1. Multi-day meetings (F-WEBEX-17): Meetings that span multiple days
           are included if they overlap with the target date.
        2. Cancelled meetings (F-WEBEX-18): Optionally filter out cancelled meetings.

        The method queries a business week range (Monday-Friday) to ensure all
        relevant meetings are captured, then filters to the specific target date.

        Args:
            target_date: The date to retrieve meetings for.
            include_cancelled: Whether to include cancelled meetings in results.

        Returns:
            List of Meeting objects for the target date, sorted by start time.
        """
        # Calculate business week range for query
        week_start, week_end = calculate_business_week_range(target_date)

        logger.info(
            "Fetching meetings for target date %s (business week: %s to %s)",
            target_date.date(),
            week_start.date(),
            week_end.date(),
        )

        # Fetch all meetings in the business week
        all_meetings = list(self.list_meetings(from_date=week_start, to_date=week_end))

        logger.debug("Retrieved %d total meetings in business week", len(all_meetings))

        # Filter meetings
        filtered_meetings: list[Meeting] = []

        for meeting in all_meetings:
            # Filter cancelled meetings if requested (F-WEBEX-18)
            if not include_cancelled and meeting.state == "cancelled":
                logger.debug("Skipping cancelled meeting: %s", meeting.title)
                continue

            # Check if meeting occurs on target date (handles multi-day
            # meetings - F-WEBEX-17)
            if is_meeting_on_date(meeting, target_date):
                filtered_meetings.append(meeting)
                logger.debug(
                    "Including meeting '%s' (starts: %s, ends: %s)",
                    meeting.title,
                    meeting.start,
                    meeting.end,
                )

        # Sort by start time
        filtered_meetings.sort(key=lambda m: m.start)

        logger.info(
            "Found %d meetings for target date %s",
            len(filtered_meetings),
            target_date.date(),
        )

        return filtered_meetings

    def get_business_week_meetings(
        self,
        target_date: datetime | None = None,
    ) -> list[Meeting]:
        """Get all scheduled meetings for the current business week (Mon-Fri).

        This method implements F-WEBEX-18 requirements by:
        1. Filtering meetings to the business week (Monday through Friday)
        2. Excluding cancelled meetings (only returning state="scheduled")
        3. Properly handling multi-day meetings that span the week boundaries

        Args:
            target_date: The date to calculate business week from. If None,
                uses current date.

        Returns:
            List of scheduled Meeting objects for the business week, sorted by
            start time. Only includes meetings with state="scheduled".

        Example:
            ```python
            client = MeetingsClient(access_token)
            meetings = client.get_business_week_meetings()
            # Returns only scheduled meetings for Mon-Fri of current week
            ```
        """
        # Use current date if not specified
        if target_date is None:
            target_date = datetime.now()

        # Calculate business week range (Monday 00:00 to Friday 23:59:59)
        week_start, week_end = calculate_business_week_range(target_date)

        logger.info(
            "Fetching business week meetings: %s to %s",
            week_start.date(),
            week_end.date(),
        )

        # Fetch all meetings in the business week
        all_meetings = list(self.list_meetings(from_date=week_start, to_date=week_end))

        logger.debug(
            "Retrieved %d total meetings in business week", len(all_meetings)
        )

        # Filter to only scheduled meetings (F-WEBEX-18: exclude cancelled)
        scheduled_meetings: list[Meeting] = []

        for meeting in all_meetings:
            # Only include meetings with state="scheduled"
            if meeting.state != "scheduled":
                logger.debug(
                    "Skipping non-scheduled meeting '%s' with state: %s",
                    meeting.title,
                    meeting.state,
                )
                continue

            # Handle multi-day meetings (F-WEBEX-17)
            # Check if meeting overlaps with business week at all
            meeting_start = datetime.fromisoformat(meeting.start.replace("Z", "+00:00"))
            meeting_end = datetime.fromisoformat(meeting.end.replace("Z", "+00:00"))

            # Include if meeting overlaps with business week
            if meeting_start <= week_end and meeting_end >= week_start:
                scheduled_meetings.append(meeting)
                logger.debug(
                    "Including scheduled meeting '%s' (starts: %s, ends: %s)",
                    meeting.title,
                    meeting.start,
                    meeting.end,
                )

        # Sort by start time
        scheduled_meetings.sort(key=lambda m: m.start)

        logger.info(
            "Found %d scheduled meetings for business week %s to %s",
            len(scheduled_meetings),
            week_start.date(),
            week_end.date(),
        )

        return scheduled_meetings

    def close(self) -> None:
        """Close the HTTP session and release resources.

        This method should be called when the client is no longer needed to
        properly clean up the underlying requests Session object.

        Example:
            ```python
            client = MeetingsClient(access_token)
            try:
                meetings = client.list_meetings()
                # Process meetings...
            finally:
                client.close()
            ```

        Alternatively, use as a context manager:
            ```python
            # Note: Context manager support would require __enter__/__exit__
            # For now, explicit close() is the recommended pattern
            ```
        """
        if self.session:
            self.session.close()
            logger.debug("MeetingsClient session closed")
