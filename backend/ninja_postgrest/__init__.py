"""ninja_postgrest — PostgREST-compatible endpoints for Django-Ninja.

Given a ``NINJA_POSTGREST`` settings dict that maps table names to Django models,
this app builds a Django-Ninja :class:`~ninja.Router` exposing PostgREST-style
REST endpoints (horizontal/vertical filtering, ordering, pagination, CRUD and
resource embedding). It respects django-guardian object-level permissions and
django-ninja authentication mechanisms.

Typical usage in a project's ``api.py``::

    from ninja_postgrest import build_router

    api.add_router("/pg/", build_router())
"""

from .exceptions import PostgrestError


__all__ = ["PostgrestError", "build_router"]

__version__ = "0.1.0"


def build_router(*args, **kwargs):
    """Build and return a Ninja ``Router`` exposing the configured tables.

    Thin lazy wrapper around :func:`ninja_postgrest.router.build_router` so that
    importing this package does not pull in Django models before the app
    registry is ready.
    """
    from .router import build_router as _build_router

    return _build_router(*args, **kwargs)
