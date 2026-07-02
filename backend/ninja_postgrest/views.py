"""Generic PostgREST view factories, one set per registered table."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from django.core.exceptions import FieldDoesNotExist
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Model
from django.http import HttpRequest, HttpResponse, JsonResponse

from .conf import get_global_config
from .exceptions import PostgrestError, postgrest_endpoint
from .headers import content_range, parse_prefer, wants_single_object
from .parsing import parse_request
from .permissions import filter_writable, require_change_object, require_create
from .query import build_read_queryset, slice_queryset
from .registry import TableConfig
from .serialization import serialize_instance


def _user(request: HttpRequest):
    return getattr(request, "user", None)


def _json_response(data: Any, *, status: int = 200) -> JsonResponse:
    return JsonResponse(
        data,
        status=status,
        safe=not isinstance(data, list),
        encoder=DjangoJSONEncoder,
    )


def _load_body(request: HttpRequest) -> Any:
    if not request.body:
        return None
    try:
        return json.loads(request.body)
    except json.JSONDecodeError as exc:
        raise PostgrestError(
            f"Invalid JSON body: {exc}",
            status=400,
            code="PGRST-400",
        ) from exc


def _writable_keys(table: TableConfig) -> dict[str, str]:
    """Map every accepted request key to the model attribute to set.

    Accepts both the field name (``pipeline``) and, for relations, the column
    name (``pipeline_id``).
    """
    mapping: dict[str, str] = {}
    for fname in table.writable:
        field = table.model._meta.get_field(fname)
        if field.is_relation and (field.many_to_one or field.one_to_one):
            mapping[field.attname] = field.attname  # pipeline_id
            mapping[field.name] = field.attname  # pipeline -> pipeline_id
        else:
            mapping[field.name] = field.name
    return mapping


def _apply_data(obj: Model, table: TableConfig, data: dict[str, Any]) -> None:
    allowed = _writable_keys(table)
    for key, value in data.items():
        if key not in allowed:
            raise PostgrestError(
                f"Column {key!r} is not writable on table {table.name!r}",
                status=400,
                code="PGRST-400",
                hint=f"Writable columns: {sorted(set(allowed))}",
            )
        setattr(obj, allowed[key], value)


def _single_object_or_406(rows: list) -> Any:
    """Return the sole row for a singular response, or raise 406.

    Mirrors PostgREST: ``Accept: application/vnd.pgrst.object+json`` demands
    exactly one row.
    """
    if len(rows) != 1:
        raise PostgrestError(
            "JSON object requested, but query did not return exactly one row",
            status=406,
            details=f"Results contain {len(rows)} rows",
            code="PGRST-406",
        )
    return rows[0]


def _column_attname(table: TableConfig, token: str) -> str:
    """Resolve an ``on_conflict`` token (field name or column name) to an attname."""
    try:
        return table.model._meta.get_field(token).attname
    except FieldDoesNotExist:
        pass
    for f in table.model._meta.get_fields():
        if getattr(f, "attname", None) == token:
            return token
    raise PostgrestError(
        f"Unknown on_conflict column {token!r} on table {table.name!r}",
        status=400,
        code="PGRST-400",
    )


def _conflict_attnames(request: HttpRequest, table: TableConfig) -> list[str]:
    """The ``on_conflict`` columns as attnames, or ``[]`` when unspecified."""
    raw = request.GET.get("on_conflict", "").strip()
    if not raw:
        return []
    return [
        _column_attname(table, tok.strip()) for tok in raw.split(",") if tok.strip()
    ]


def _upsert_rows(
    user,
    table: TableConfig,
    items: list,
    conflict: list[str],
    resolution: str,
) -> list[Model]:
    """Insert-or-update each row, keyed on the ``on_conflict`` columns.

    ``merge-duplicates`` updates the conflicting row from the remaining body
    columns; ``ignore-duplicates`` leaves an existing row untouched. Uses
    ``update_or_create`` / ``get_or_create`` so the behaviour is identical on
    every backend and real instances are returned for the representation.

    Inserting is gated by ``require_create`` (the model-level ``add`` perm) at
    the view; updating an existing row additionally requires ``change`` on that
    row, so ``add``-only callers cannot mutate rows they may not change.
    """
    allowed = _writable_keys(table)
    manager = table.model._default_manager
    ignore = resolution == "ignore-duplicates"
    out: list[Model] = []
    for data in items:
        lookup: dict[str, Any] = {}
        defaults: dict[str, Any] = {}
        for key, value in data.items():
            if key not in allowed:
                raise PostgrestError(
                    f"Column {key!r} is not writable on table {table.name!r}",
                    status=400,
                    code="PGRST-400",
                    hint=f"Writable columns: {sorted(set(allowed))}",
                )
            target = lookup if allowed[key] in conflict else defaults
            target[allowed[key]] = value
        missing = [c for c in conflict if c not in lookup]
        if missing:
            raise PostgrestError(
                f"on_conflict column(s) {missing} missing from row",
                status=400,
                code="PGRST-400",
            )
        if ignore:
            obj, _ = manager.get_or_create(defaults=defaults, **lookup)
        else:
            existing = manager.filter(**lookup).first()
            if existing is not None:
                require_change_object(user, table, existing)
            obj, _ = manager.update_or_create(defaults=defaults, **lookup)
        out.append(obj)
    return out


# --------------------------------------------------------------------------- #
# GET (list / single)
# --------------------------------------------------------------------------- #
def make_list_view(table: TableConfig) -> Callable:
    @postgrest_endpoint
    def view(request: HttpRequest):
        gc = get_global_config()
        parsed = parse_request(request, table)
        prefer = parse_prefer(request)
        qs = build_read_queryset(table, parsed, _user(request))

        total = qs.count() if prefer.count == "exact" else None
        page = slice_queryset(
            qs,
            parsed.offset,
            parsed.limit,
            gc.max_limit,
            gc.default_limit,
        )
        rows = [serialize_instance(obj, table, parsed.select) for obj in page]

        if wants_single_object(request):
            return _json_response(_single_object_or_406(rows))

        resp = _json_response(rows)
        resp["Content-Range"] = content_range(parsed.offset, len(rows), total)
        return resp

    view.__name__ = f"list_{table.name}"
    return view


# --------------------------------------------------------------------------- #
# POST (create)
# --------------------------------------------------------------------------- #
def make_create_view(table: TableConfig) -> Callable:
    @postgrest_endpoint
    def view(request: HttpRequest):
        require_create(_user(request), table)
        prefer = parse_prefer(request)
        payload = _load_body(request)
        is_bulk = isinstance(payload, list)
        items = payload if is_bulk else [payload]
        for data in items:
            if not isinstance(data, dict):
                raise PostgrestError("Each row must be a JSON object", status=400)

        # An upsert (Prefer: resolution=...) needs an on_conflict target to key
        # on; without one it degrades to a plain insert, mirroring PostgREST
        # when no conflict target can be inferred.
        conflict = _conflict_attnames(request, table) if prefer.resolution else []
        created: list[Model] = []
        with transaction.atomic():
            if conflict:
                created = _upsert_rows(
                    _user(request),
                    table,
                    items,
                    conflict,
                    prefer.resolution,
                )
            else:
                for data in items:
                    obj = table.model()
                    _apply_data(obj, table, data)
                    obj.save()
                    created.append(obj)

        if not prefer.return_representation:
            return HttpResponse(status=201)
        # PostgREST returns an array whether one row or many were inserted; the
        # singular media type (Accept) collapses it to one object.
        rows = [serialize_instance(obj, table, None) for obj in created]
        if wants_single_object(request):
            return _json_response(_single_object_or_406(rows), status=201)
        return _json_response(rows, status=201)

    view.__name__ = f"create_{table.name}"
    return view


# --------------------------------------------------------------------------- #
# PATCH (update)
# --------------------------------------------------------------------------- #
def make_update_view(table: TableConfig) -> Callable:
    @postgrest_endpoint
    def view(request: HttpRequest):
        prefer = parse_prefer(request)
        parsed = parse_request(request, table)
        data = _load_body(request)
        if not isinstance(data, dict):
            raise PostgrestError("PATCH body must be a JSON object", status=400)

        qs = table.model._default_manager.all().filter(parsed.q)
        qs = filter_writable(_user(request), table, qs, "update")

        updated: list[Model] = []
        with transaction.atomic():
            for obj in qs.select_for_update():
                _apply_data(obj, table, data)
                obj.save()
                updated.append(obj)

        if not prefer.return_representation:
            return HttpResponse(status=204)
        rows = [serialize_instance(obj, table, parsed.select) for obj in updated]
        return _json_response(rows)

    view.__name__ = f"update_{table.name}"
    return view


# --------------------------------------------------------------------------- #
# DELETE
# --------------------------------------------------------------------------- #
def make_delete_view(table: TableConfig) -> Callable:
    @postgrest_endpoint
    def view(request: HttpRequest):
        prefer = parse_prefer(request)
        parsed = parse_request(request, table)

        qs = table.model._default_manager.all().filter(parsed.q)
        qs = filter_writable(_user(request), table, qs, "delete")

        rows = None
        if prefer.return_representation:
            rows = [serialize_instance(obj, table, parsed.select) for obj in qs]
        qs.delete()

        if rows is None:
            return HttpResponse(status=204)
        return _json_response(rows)

    view.__name__ = f"delete_{table.name}"
    return view


__all__ = [
    "make_create_view",
    "make_delete_view",
    "make_list_view",
    "make_update_view",
]
