"""Pydantic/Ninja schema generation for documentation purposes.

Responses are emitted as raw JSON (their shape depends on the dynamic
``select``), so these schemas are used only to document the *full-row*
representation in the OpenAPI spec. They are generated once per table and cached.
"""

from __future__ import annotations

from ninja.orm import create_schema

from .registry import TableConfig

_schema_cache: dict[str, type] = {}


def get_full_schema(table: TableConfig) -> type:
    """Return a cached Ninja ``Schema`` describing the table's full row."""
    if table.name not in _schema_cache:
        # ``table.fields`` holds attnames (e.g. ``pipeline_id`` for a FK) to
        # match PostgREST's flat columns, but ``create_schema``'s ``fields``
        # looks fields up by Django field ``name`` (e.g. ``pipeline``), and
        # sets the attname as the field's pydantic alias. Translating back to
        # ``name`` here lets ``create_schema`` build the field at all; the
        # flat column is only actually *surfaced* (including in the generated
        # OpenAPI docs) because the GET operation is registered with
        # ``by_alias=True`` (see router.py), which makes serialization and
        # schema generation honor the ``pipeline_id`` alias over ``pipeline``.
        name_by_attname = {f.attname: f.name for f in table.model._meta.concrete_fields}
        fields = [name_by_attname.get(f, f) for f in table.fields]
        _schema_cache[table.name] = create_schema(
            table.model,
            name=f"Postgrest_{table.model.__name__}",
            fields=fields,
        )
    return _schema_cache[table.name]


def reset_schema_cache() -> None:
    _schema_cache.clear()
