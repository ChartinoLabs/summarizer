from typing import Any

import requests

class webexpythonsdkException(Exception): ...  # noqa: N801, N818
class webexpythonsdkWarning(webexpythonsdkException, Warning): ...  # noqa: N801
class AccessTokenError(webexpythonsdkException): ...

class ApiError(webexpythonsdkException):
    response: requests.Response
    request: Any
    status_code: int
    status: str
    description: str | None
    details: dict[str, Any] | None
    message: str | None
    tracking_id: str | None
    error_message: str
    def __init__(self, response: requests.Response) -> None: ...
    def __repr__(self) -> str: ...

class ApiWarning(webexpythonsdkWarning, ApiError): ...  # noqa: N818

class RateLimitError(ApiError):
    retry_after: int
    def __init__(self, response: requests.Response) -> None: ...

class RateLimitWarning(ApiWarning, RateLimitError): ...  # noqa: N818
class MalformedResponse(webexpythonsdkException): ...
