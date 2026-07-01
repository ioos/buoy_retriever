"""Assemble a final queryset from a parsed request + permission filtering."""

from __future__ import annotations

from django.db.models import QuerySet

from .embedding import apply_embeds
from .parsing import ParsedQuery
from .permissions import filter_readable
from .registry import TableConfig


def build_read_queryset(table: TableConfig, parsed: ParsedQuery, user) -> QuerySet:
    """Build the queryset for a GET: permission filter, horizontal filter,
    embeds and ordering. Slicing (limit/offset) is applied by the caller after
    optionally counting."""
    qs = table.model._default_manager.all()
    qs = filter_readable(user, table, qs)
    qs = qs.filter(parsed.q)
    qs = apply_embeds(qs, table, parsed.select, user)
    if parsed.order:
        qs = qs.order_by(*parsed.order)
    return qs


def slice_queryset(
    qs: QuerySet,
    offset: int,
    limit: int | None,
    max_limit: int,
) -> QuerySet:
    """Apply offset/limit honouring the configured ``MAX_LIMIT`` cap."""
    effective_limit = max_limit if limit is None else min(limit, max_limit)
    return qs[offset : offset + effective_limit]
