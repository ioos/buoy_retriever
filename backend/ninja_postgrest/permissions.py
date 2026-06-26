"""Permission strategies layered on top of django-ninja auth.

Three modes (per table, defaulting to the global ``DEFAULT_PERMISSIONS``):

- ``guardian`` — object-level filtering via django-guardian. Lists/reads are
  filtered to objects the user may ``view``; updates/deletes to objects they may
  ``change`` / ``delete``; creates require the model-level ``add`` perm.
- ``model`` — plain ``user.has_perm('app.view_model')`` checks, no per-object
  filtering.
- ``open`` — no permission checks (ninja ``auth`` still applies).
"""

from __future__ import annotations

from django.db.models import QuerySet

from .exceptions import PostgrestError
from .registry import TableConfig


def _deny(action: str, table: TableConfig) -> PostgrestError:
    return PostgrestError(
        f"You do not have permission to {action} on table {table.name!r}",
        status=403,
        code="PGRST-403",
    )


def filter_readable(user, table: TableConfig, qs: QuerySet) -> QuerySet:
    """Restrict a queryset to rows the user may read."""
    mode = table.permissions
    if mode == "open":
        return qs
    perm = table.perm_codename("list")
    if mode == "guardian":
        from guardian.shortcuts import get_objects_for_user

        return get_objects_for_user(user, perm, klass=qs, accept_global_perms=True)
    # model mode
    if not user.has_perm(perm):
        return qs.none()
    return qs


def filter_writable(user, table: TableConfig, qs: QuerySet, action: str) -> QuerySet:
    """Restrict a queryset to rows the user may ``update`` / ``delete``."""
    mode = table.permissions
    if mode == "open":
        return qs
    perm = table.perm_codename(action)
    if mode == "guardian":
        from guardian.shortcuts import get_objects_for_user

        return get_objects_for_user(user, perm, klass=qs, accept_global_perms=True)
    if not user.has_perm(perm):
        return qs.none()
    return qs


def require_create(user, table: TableConfig) -> None:
    """Raise unless the user may create rows (model-level ``add`` perm)."""
    if table.permissions == "open":
        return
    perm = table.perm_codename("create")
    if not user.has_perm(perm):
        raise _deny("create", table)
