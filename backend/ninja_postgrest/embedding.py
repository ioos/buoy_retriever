"""Plan related-object fetching for ``select`` embeds.

A relation may only be embedded when BOTH (a) it is listed in the table's
``embeddable`` config and (b) its related model is itself registered in
``NINJA_POSTGREST['TABLES']``. Embedding a relation whose model is not registered
is explicitly denied (400) — there is no policy under which to expose it.

Forward relations (FK / O2O) use ``select_related``; reverse relations and M2M
use a permission-filtered ``prefetch_related``.

v1 limitation: forward (FK/O2O) embeds are NOT additionally permission-filtered
— the parent row is already authorized and we do not hide forward-referenced
rows. Reverse/M2M embeds ARE filtered.
"""

from __future__ import annotations

from django.db.models import Prefetch, QuerySet

from .exceptions import PostgrestError
from .parsing import SelectEmbed
from .registry import TableConfig, get_table_for_model


def _relation_field(model, accessor: str):
    for f in model._meta.get_fields():
        name = f.get_accessor_name() if hasattr(f, "get_accessor_name") else f.name
        if name == accessor or getattr(f, "name", None) == accessor:
            return f
    return None


def apply_embeds(
    qs: QuerySet,
    table: TableConfig | None,
    select: list | None,
    user,
) -> QuerySet:
    """Attach select_related / prefetch_related derived from ``select`` embeds."""
    if not select:
        return qs

    select_related: list[str] = []
    prefetches: list[Prefetch] = []

    for node in select:
        if not isinstance(node, SelectEmbed):
            continue

        if table is not None and node.relation not in table.embeddable:
            raise PostgrestError(
                f"Relation {node.relation!r} is not embeddable on table "
                f"{table.name!r} (allowed: {sorted(table.embeddable)})",
                status=400,
                code="PGRST-400",
            )

        model = qs.model
        field = _relation_field(model, node.relation)
        if field is None:
            raise PostgrestError(
                f"Unknown relation {node.relation!r} on {model.__name__}",
                status=400,
                code="PGRST-400",
            )

        # The related model must be a registered table, otherwise there is no
        # permission policy under which to expose it: deny explicitly.
        related_model = field.related_model
        related_table = get_table_for_model(related_model)
        if related_table is None:
            raise PostgrestError(
                f"Cannot embed {node.relation!r}: its model "
                f"{related_model.__name__!r} is not a registered table",
                status=400,
                code="PGRST-400",
            )

        if field.many_to_one or field.one_to_one:
            select_related.append(node.relation)
            continue

        from .permissions import filter_readable

        rel_qs = filter_readable(
            user,
            related_table,
            related_model._default_manager.all(),
        )
        rel_qs = apply_embeds(rel_qs, related_table, node.children or None, user)
        prefetches.append(Prefetch(node.relation, queryset=rel_qs))

    if select_related:
        qs = qs.select_related(*select_related)
    if prefetches:
        qs = qs.prefetch_related(*prefetches)
    return qs
