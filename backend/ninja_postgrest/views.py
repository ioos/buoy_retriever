"""Generic PostgREST view factories, one set per registered table."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Model
from django.http import HttpRequest, HttpResponse, JsonResponse

from .conf import get_global_config
from .exceptions import PostgrestError, postgrest_endpoint
from .headers import content_range, parse_prefer, wants_single_object
from .parsing import parse_request
from .permissions import filter_writable, require_create
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
        page = slice_queryset(qs, parsed.offset, parsed.limit, gc.max_limit)
        rows = [serialize_instance(obj, table, parsed.select) for obj in page]

        if wants_single_object(request):
            if len(rows) != 1:
                raise PostgrestError(
                    "JSON object requested, but query did not return exactly one row",
                    status=406,
                    details=f"Results contain {len(rows)} rows",
                    code="PGRST-406",
                )
            return _json_response(rows[0])

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

        created: list[Model] = []
        with transaction.atomic():
            for data in items:
                if not isinstance(data, dict):
                    raise PostgrestError("Each row must be a JSON object", status=400)
                obj = table.model()
                _apply_data(obj, table, data)
                obj.save()
                created.append(obj)

        if not prefer.return_representation:
            return HttpResponse(status=201)
        rows = [serialize_instance(obj, table, None) for obj in created]
        return _json_response(rows if is_bulk else rows[0], status=201)

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
