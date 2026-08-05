"""MAL API client package."""

from backend.app.mal.client import MalClient
from backend.app.mal.errors import (
    MalAuthenticationError,
    MalAuthorizationError,
    MalError,
    MalNotFoundError,
    MalRateLimitError,
    MalTemporaryError,
    MalUnexpectedResponseError,
    MalValidationError,
)

__all__ = [
    "MalAuthenticationError",
    "MalAuthorizationError",
    "MalClient",
    "MalError",
    "MalNotFoundError",
    "MalRateLimitError",
    "MalTemporaryError",
    "MalUnexpectedResponseError",
    "MalValidationError",
]
