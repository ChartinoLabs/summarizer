from collections.abc import Generator

from .models.immutable import Membership, Message, Person, Room

class WebexAPI:
    def __init__(self, access_token: str) -> None: ...
    @property
    def people(self) -> PeopleAPI: ...
    @property
    def rooms(self) -> RoomsAPI: ...
    @property
    def messages(self) -> MessagesAPI: ...
    @property
    def memberships(self) -> MembershipsAPI: ...

class PeopleAPI:
    def me(self) -> Person: ...
    def get(self, personId: str) -> Person: ...  # noqa: N803

class RoomsAPI:
    def list(
        self,
        max: int = ...,
        sortBy: str = ...,  # noqa: N803
    ) -> Generator[Room, None, None]: ...
    def get(self, roomId: str) -> Room: ...  # noqa: N803

class MessagesAPI:
    def list(
        self,
        roomId: str,  # noqa: N803
        max: int = ...,
    ) -> Generator[Message, None, None]: ...

class MembershipsAPI:
    def list(
        self,
        roomId: str,  # noqa: N803
        max: int = ...,
    ) -> Generator[Membership, None, None]: ...
