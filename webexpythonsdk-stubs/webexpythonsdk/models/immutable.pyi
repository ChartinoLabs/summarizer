from datetime import datetime

class Message:
    id: str
    roomId: str  # noqa: N803, N815
    personEmail: str  # noqa: N803, N815
    text: str
    created: datetime

class Person:
    id: str
    displayName: str  # noqa: N803, N815
    emails: list[str]

class Room:
    id: str
    title: str
