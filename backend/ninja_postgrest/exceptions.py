"""PostgREST-compatible error type and response helpers.

PostgREST returns JSON error bodies of the shape::

    {"message": "...", "details": "...", "hint": "...", "code": "..."}

We mirror that shape. Endpoints are wrapped with :func:`postgrest_endpoint`
which turns a raised :class:`PostgrestError` into the appropriate JSON response,
so the app stays self-contained and does not need to mutate the consumer's
``NinjaAPI`` instance with exception handlers.
"""

from __future__ import annotations

import functools
from collections.abc import Callable

from django.http import JsonResponse


class PostgrestError(Exception):
    """An error to return to the client in PostgREST's JSON error format."""

    def __init__(
        self,
        message: str,
        *,
        status: int = 400,
        details: str | None = None,
        hint: str | None = None,
        code: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.details = details
        self.hint = hint
        self.code = code

    def to_dict(self) -> dict[str, str | None]:
        return {
            "message": self.message,
            "details": self.details,
            "hint": self.hint,
            "code": self.code,
        }

    def to_response(self) -> JsonResponse:
        return JsonResponse(self.to_dict(), status=self.status)


def postgrest_endpoint(func: Callable) -> Callable:
    """Wrap a view so raised :class:`PostgrestError` becomes a JSON response."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except PostgrestError as exc:
            return exc.to_response()

    return wrapper
