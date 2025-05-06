from datetime import datetime
from typing import Literal

class Message:
    id: str
    roomId: str  # noqa: N803, N815
    personEmail: str  # noqa: N803, N815
    personId: str  # noqa: N803, N815
    text: str
    created: datetime | None

class Person:
    id: str
    displayName: str  # noqa: N803, N815
    emails: list[str]

RoomType = Literal["direct", "group"]

class Room:
    id: str
    title: str
    type: RoomType
