"""Parsing of PostgREST request headers and building the ``Content-Range``
response header."""

from __future__ import annotations

from dataclasses import dataclass

from django.http import HttpRequest

SINGULAR_MEDIA_TYPE = "application/vnd.pgrst.object+json"


@dataclass
class Prefer:
    count: str | None = None  # "exact" | "planned" | "estimated"
    return_representation: bool = False
    resolution: str | None = None  # "merge-duplicates" | "ignore-duplicates"


def parse_prefer(request: HttpRequest) -> Prefer:
    raw = request.headers.get("Prefer", "")
    prefer = Prefer()
    for part in raw.split(","):
        token = part.strip()
        if not token:
            continue
        key, _, value = token.partition("=")
        key, value = key.strip(), value.strip()
        if key == "count":
            prefer.count = value
        elif key == "return":
            prefer.return_representation = value == "representation"
        elif key == "resolution":
            prefer.resolution = value
    return prefer


def wants_single_object(request: HttpRequest) -> bool:
    """True when the client requested a singular response via Accept."""
    return SINGULAR_MEDIA_TYPE in request.headers.get("Accept", "")


def parse_range(request: HttpRequest) -> tuple[int | None, int | None]:
    """Parse a ``Range: 0-9`` header into ``(offset, limit)``.

    Returns ``(None, None)`` when absent or unparsable.
    """
    raw = request.headers.get("Range", "")
    if not raw:
        return None, None
    spec = raw.split("=", 1)[-1].strip()  # tolerate "items=0-9"
    start_s, sep, end_s = spec.partition("-")
    if not sep:
        return None, None
    try:
        start = int(start_s)
    except ValueError:
        return None, None
    if not end_s:
        return start, None
    try:
        end = int(end_s)
    except ValueError:
        return start, None
    return start, end - start + 1


def content_range(offset: int, returned: int, total: int | None) -> str:
    """Build a ``Content-Range`` value like ``0-9/42`` or ``0-9/*``.

    An empty page is rendered as ``*/<total>`` per PostgREST convention.
    """
    total_part = "*" if total is None else str(total)
    if returned == 0:
        return f"*/{total_part}"
    end = offset + returned - 1
    return f"{offset}-{end}/{total_part}"
