"""Build a Django-Ninja router exposing the configured tables as PostgREST
endpoints.

Routes are registered dynamically (table names come from settings) via
``Router.add_api_operation`` rather than decorators.
"""

from __future__ import annotations

from django.http import HttpRequest, JsonResponse
from ninja import Router

from .conf import UNSET
from .registry import TableConfig, get_registry


def _auth_kwargs(table: TableConfig) -> dict:
    """Translate a resolved auth value into kwargs for ``add_api_operation``.

    ``UNSET`` means "inherit Ninja's default" (omit the kwarg); anything else
    (including ``None`` to disable auth) is passed through verbatim.
    """
    if table.auth is UNSET:
        return {}
    return {"auth": table.auth}


def build_router(router: Router | None = None) -> Router:
    """Create (or extend) a ``Router`` with operations for every configured table."""
    router = router or Router()
    registry = get_registry()

    @router.get("/", include_in_schema=False)
    def index(request: HttpRequest):
        """List the table names exposed by this router."""
        return {"tables": sorted(registry.keys())}

    for table in registry.values():
        _register_table(router, table)

    return router


def _register_table(router: Router, table: TableConfig) -> None:
    # Per-table views are wired up in later milestones (read core / writes).
    # Import lazily so the module graph stays acyclic and optional pieces can be
    # added incrementally.
    from . import views

    auth = _auth_kwargs(table)
    path = f"/{table.name}"

    if table.supports_get:
        router.add_api_operation(
            path,
            ["GET"],
            views.make_list_view(table),
            **auth,
        )
    if table.allows("create"):
        router.add_api_operation(path, ["POST"], views.make_create_view(table), **auth)
    if table.allows("update"):
        router.add_api_operation(path, ["PATCH"], views.make_update_view(table), **auth)
    if table.allows("delete"):
        router.add_api_operation(
            path,
            ["DELETE"],
            views.make_delete_view(table),
            **auth,
        )


__all__ = ["build_router", "JsonResponse"]
