"""Render model instances to JSON-able dicts according to a parsed ``select``."""

from __future__ import annotations

from typing import Any

from django.core.exceptions import FieldDoesNotExist
from django.db.models import Model

from .parsing import SelectEmbed, SelectField
from .registry import TableConfig, get_table_for_model


def _scalar_key_value(instance: Model, field_name: str) -> tuple[str, Any]:
    """Return the output ``(key, value)`` for a concrete field.

    Foreign keys are serialised as their scalar id column (``pipeline_id``),
    mirroring PostgREST's flat table columns.
    """
    field = instance._meta.get_field(field_name)
    if field.is_relation and (field.many_to_one or field.one_to_one):
        return field.attname, getattr(instance, field.attname)
    return field.name, getattr(instance, field.name)


def _dig_json(value: Any, path: list[str]) -> Any:
    for seg in path:
        if value is None:
            return None
        if isinstance(value, dict):
            value = value.get(seg)
        elif isinstance(value, list):
            try:
                value = value[int(seg)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return value


def _serialize_field(instance: Model, node: SelectField) -> tuple[str, Any]:
    value = getattr(instance, node.column, None)
    if node.json_path:
        value = _dig_json(value, node.json_path)
    else:
        # Resolve FK scalar id when selecting the relation field by name.
        try:
            field = instance._meta.get_field(node.column)
        except FieldDoesNotExist:
            field = None
        if (
            field is not None
            and field.is_relation
            and (field.many_to_one or field.one_to_one)
        ):
            value = getattr(instance, field.attname)
    return node.output_key, value


def _default_fields(table: TableConfig | None, instance: Model) -> list[str]:
    if table is not None:
        return list(table.fields)
    return [f.name for f in instance._meta.concrete_fields]


def serialize_instance(
    instance: Model,
    table: TableConfig | None,
    select: list | None,
) -> dict[str, Any]:
    """Serialize one instance per the ``select`` tree (or all configured fields)."""
    out: dict[str, Any] = {}

    if select is None:
        for fname in _default_fields(table, instance):
            key, value = _scalar_key_value(instance, fname)
            out[key] = value
        return out

    for node in select:
        if isinstance(node, SelectField):
            key, value = _serialize_field(instance, node)
            out[key] = value
        elif isinstance(node, SelectEmbed):
            out[node.output_key] = _serialize_embed(instance, node)
    return out


def _serialize_embed(instance: Model, node: SelectEmbed) -> Any:
    related_obj = getattr(instance, node.relation, None)
    field = _get_relation(instance, node.relation)
    related_model = _related_model(field)
    related_table = get_table_for_model(related_model) if related_model else None
    child_select = node.children or None

    if field is not None and (field.many_to_one or field.one_to_one):
        # Forward FK / O2O -> single object (or null).
        if related_obj is None:
            return None
        return serialize_instance(related_obj, related_table, child_select)

    # Reverse FK / M2M -> manager (queryset already permission-filtered by the
    # prefetch planner in embedding.py).
    if related_obj is None:
        return []
    manager = related_obj
    queryset = manager.all() if hasattr(manager, "all") else manager
    return [serialize_instance(obj, related_table, child_select) for obj in queryset]


def _get_relation(instance: Model, accessor: str):
    for f in instance._meta.get_fields():
        name = f.get_accessor_name() if hasattr(f, "get_accessor_name") else f.name
        if name == accessor or getattr(f, "name", None) == accessor:
            return f
    return None


def _related_model(field) -> type[Model] | None:
    if field is None:
        return None
    return field.related_model
