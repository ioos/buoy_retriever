"""Custom Django lookups backing the PostgREST ``like`` / ``ilike`` operators.

PostgREST's ``like`` and ``ilike`` use SQL ``LIKE``/``ILIKE`` semantics with
``*`` standing in for ``%``. Django has no built-in lookup that exposes a raw
``LIKE`` with caller-supplied wildcards (``__contains`` escapes them), so we
register thin lookups that emit ``LIKE`` / ``ILIKE`` directly.
"""

from __future__ import annotations

from django.db.models import Field, Lookup


class Like(Lookup):
    lookup_name = "like"

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        return f"{lhs} LIKE {rhs}", (*lhs_params, *rhs_params)


class ILike(Lookup):
    lookup_name = "ilike"

    def as_sql(self, compiler, connection):
        lhs, lhs_params = self.process_lhs(compiler, connection)
        rhs, rhs_params = self.process_rhs(compiler, connection)
        # SQLite has no ILIKE; fall back to a case-insensitive LIKE there.
        if connection.vendor == "sqlite":
            return f"{lhs} LIKE {rhs}", (*lhs_params, *rhs_params)
        return f"{lhs} ILIKE {rhs}", (*lhs_params, *rhs_params)


_registered = False


def register_lookups() -> None:
    """Register the lookups on ``Field`` so they apply to every field type.

    Idempotent: safe to call more than once (e.g. from ``AppConfig.ready``).
    """
    global _registered
    if _registered:
        return
    Field.register_lookup(Like)
    Field.register_lookup(ILike)
    _registered = True
