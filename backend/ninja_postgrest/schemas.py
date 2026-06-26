"""Pydantic/Ninja schema generation for documentation purposes.

Responses are emitted as raw JSON (their shape depends on the dynamic
``select``), so these schemas are used only to document the *full-row*
representation in the OpenAPI spec. They are generated once per table and cached.
"""

from __future__ import annotations

from typing import Any

from ninja.orm import create_schema

from .registry import TableConfig

_schema_cache: dict[str, type] = {}


def get_full_schema(table: TableConfig) -> type:
    """Return a cached Ninja ``Schema`` describing the table's full row."""
    if table.name not in _schema_cache:
        _schema_cache[table.name] = create_schema(
            table.model,
            name=f"Postgrest_{table.model.__name__}",
            fields=list(table.fields),
        )
    return _schema_cache[table.name]


def reset_schema_cache() -> None:
    _schema_cache.clear()


# A loose object type for request bodies (create/update accept arbitrary columns).
JsonBody = dict[str, Any]
