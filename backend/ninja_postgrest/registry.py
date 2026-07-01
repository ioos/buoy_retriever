"""Table registry: turns the ``NINJA_POSTGREST['TABLES']`` mapping into
validated :class:`TableConfig` objects keyed by the exposed table name."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.apps import apps
from django.db.models import Field, Model

from .conf import UNSET, GlobalConfig, TableInputConfig, load_global_config

ALL_OPERATIONS = ("list", "read", "create", "update", "delete")

# Maps a CRUD action to the Django permission action verb used to build a
# default permission codename (``<app_label>.<verb>_<model_name>``).
ACTION_TO_PERM_VERB = {
    "list": "view",
    "read": "view",
    "create": "add",
    "update": "change",
    "delete": "delete",
}


def _resolve_model(model_ref: Any) -> type[Model]:
    if isinstance(model_ref, str):
        return apps.get_model(model_ref)
    if isinstance(model_ref, type) and issubclass(model_ref, Model):
        return model_ref
    msg = f"Cannot resolve model from {model_ref!r}; use 'app_label.Model' or a Model class"
    raise TypeError(msg)


def _concrete_field_names(model: type[Model]) -> list[str]:
    """Exposed scalar columns: the ``attname`` (so FKs appear as ``pipeline_id``,
    matching PostgREST's flat table columns)."""
    return [f.attname for f in model._meta.concrete_fields]


def _valid_field_tokens(model: type[Model]) -> set[str]:
    """Field names accepted in config: both ``name`` and ``attname``."""
    tokens: set[str] = set()
    for f in model._meta.concrete_fields:
        tokens.add(f.name)
        tokens.add(f.attname)
    return tokens


def _relation_accessor_names(model: type[Model]) -> set[str]:
    """Names usable in ``select`` embeds: forward and reverse relations."""
    names: set[str] = set()
    for rel in model._meta.get_fields():
        if rel.is_relation:
            # ``get_accessor_name`` exists on reverse relations; forward
            # relations expose their attribute via ``.name``.
            accessor = getattr(rel, "get_accessor_name", None)
            names.add(accessor() if callable(accessor) else rel.name)
    return names


def _is_writable_default(f: Field) -> bool:
    if f.primary_key:
        return False
    if getattr(f, "auto_created", False):
        return False
    if getattr(f, "auto_now", False) or getattr(f, "auto_now_add", False):
        return False
    return f.editable


def _default_permission_map(model: type[Model]) -> dict[str, str]:
    meta = model._meta
    return {
        action: f"{meta.app_label}.{verb}_{meta.model_name}"
        for action, verb in ACTION_TO_PERM_VERB.items()
    }


@dataclass
class TableConfig:
    """Resolved, validated configuration for a single exposed table."""

    name: str
    model: type[Model]
    operations: tuple[str, ...]
    fields: tuple[str, ...]
    filterable: frozenset[str]
    orderable: frozenset[str]
    writable: frozenset[str]
    embeddable: frozenset[str]
    pk: str
    permissions: str
    permission_map: dict[str, str]
    auth: Any = UNSET

    def allows(self, operation: str) -> bool:
        return operation in self.operations

    @property
    def supports_get(self) -> bool:
        return "list" in self.operations or "read" in self.operations

    def perm_codename(self, action: str) -> str:
        return self.permission_map[action]


def _build_table_config(
    name: str,
    raw: TableInputConfig,
    gc: GlobalConfig,
) -> TableConfig:
    model = _resolve_model(raw.model)
    concrete = _concrete_field_names(model)
    valid_tokens = _valid_field_tokens(model)
    relations = _relation_accessor_names(model)

    fields = tuple(raw.fields if raw.fields is not None else concrete)
    unknown = set(fields) - valid_tokens
    if unknown:
        msg = f"TABLES[{name!r}]['fields'] references unknown fields: {sorted(unknown)}"
        raise ValueError(msg)

    filterable = frozenset(raw.filterable if raw.filterable is not None else fields)
    orderable = frozenset(raw.orderable if raw.orderable is not None else fields)

    default_writable = [
        f.name for f in model._meta.concrete_fields if _is_writable_default(f)
    ]
    writable = frozenset(raw.writable if raw.writable is not None else default_writable)

    embeddable = frozenset(raw.embeddable)
    bad_embeds = embeddable - relations
    if bad_embeds:
        msg = (
            f"TABLES[{name!r}]['embeddable'] references non-relation accessors: "
            f"{sorted(bad_embeds)} (available: {sorted(relations)})"
        )
        raise ValueError(msg)

    operations = tuple(raw.operations if raw.operations is not None else ALL_OPERATIONS)

    permission_map = _default_permission_map(model)
    permission_map.update(raw.permission_map)

    permissions = (
        raw.permissions if raw.permissions is not None else gc.default_permissions
    )

    auth = raw.auth if raw.auth is not UNSET else gc.default_auth

    return TableConfig(
        name=name,
        model=model,
        operations=operations,
        fields=fields,
        filterable=filterable,
        orderable=orderable,
        writable=writable,
        embeddable=embeddable,
        pk=raw.pk if raw.pk is not None else model._meta.pk.name,
        permissions=permissions,
        permission_map=permission_map,
        auth=auth,
    )


_registry: dict[str, TableConfig] | None = None


def build_registry() -> dict[str, TableConfig]:
    gc = load_global_config()
    return {name: _build_table_config(name, raw, gc) for name, raw in gc.tables.items()}


def get_registry() -> dict[str, TableConfig]:
    """Return the (cached) table registry, building it on first access."""
    global _registry
    if _registry is None:
        _registry = build_registry()
    return _registry


def reset_registry() -> None:
    """Clear the cached registry (used by tests overriding settings)."""
    global _registry
    _registry = None


def get_table_for_model(model: type[Model]) -> TableConfig | None:
    """Return the registered TableConfig whose model is ``model`` (or None)."""
    for cfg in get_registry().values():
        if cfg.model is model:
            return cfg
    return None


def get_table(name: str) -> TableConfig:
    from .exceptions import PostgrestError

    try:
        return get_registry()[name]
    except KeyError as exc:
        raise PostgrestError(
            f"Unknown table {name!r}",
            status=404,
            code="PGRST-404",
        ) from exc
