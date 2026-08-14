"""Loading and normalisation of the ``NINJA_POSTGREST`` setting."""

from __future__ import annotations

from typing import Any, Literal

from django.conf import settings
from django.utils.module_loading import import_string
from pydantic import BaseModel, ConfigDict, Field, field_validator

Operation = Literal["list", "read", "create", "update", "delete"]
PermissionMode = Literal["guardian", "model", "open"]


class _Unset:
    """Sentinel distinguishing "not configured" from an explicit ``None``.

    An explicit ``None`` tells Django-Ninja that no authentication is required;
    ``UNSET`` means the field was never configured and nothing is passed.
    """


# Module-level singleton imported by registry.py
UNSET: Any = _Unset()


def _resolve_auth(value: Any) -> Any:
    """Resolve an auth setting into something Django-Ninja accepts.

    Accepts an import-path string, a callable/instance, a list of either, or
    ``None``. Strings are imported; lists are resolved element-wise.
    """
    if value is None or isinstance(value, _Unset):
        return value
    if isinstance(value, str):
        return import_string(value)
    if isinstance(value, (list, tuple)):
        return [_resolve_auth(item) for item in value]
    return value


class TableInputConfig(BaseModel):
    """Raw per-table settings from ``NINJA_POSTGREST['TABLES']``.

    Field lists (``fields``, ``filterable``, ``orderable``, ``writable``) are
    ``None`` by default, meaning "inherit the model-derived default" — the
    registry resolves the actual values once the Django model is available.
    """

    model_config = ConfigDict(arbitrary_types_allowed=True)

    model: Any  # "app_label.ModelName" or a Model subclass — resolved by registry
    fields: list[str] | None = None
    filterable: list[str] | None = None
    orderable: list[str] | None = None
    writable: list[str] | None = None
    embeddable: list[str] = Field(default_factory=list)
    operations: list[Operation] | None = None
    permissions: PermissionMode | None = None
    permission_map: dict[str, str] = Field(default_factory=dict)
    auth: Any = UNSET
    pk: str | None = None

    @field_validator("auth", mode="before")
    @classmethod
    def resolve_auth_strings(cls, v: Any) -> Any:
        return _resolve_auth(v)


class GlobalConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    default_auth: Any = UNSET
    default_permissions: PermissionMode = "guardian"
    max_limit: int = 1000
    default_limit: int | None = None
    tables: dict[str, TableInputConfig] = Field(default_factory=dict)

    @field_validator("default_auth", mode="before")
    @classmethod
    def resolve_auth_strings(cls, v: Any) -> Any:
        return _resolve_auth(v)

    @field_validator("tables", mode="before")
    @classmethod
    def normalize_tables(cls, v: Any) -> dict:
        if not v:
            return {}
        result = {}
        for k, val in v.items():
            if isinstance(val, (str, type)):
                result[k] = {"model": val}
            elif isinstance(val, dict):
                result[k] = val
            else:
                msg = f"TABLES[{k!r}] must be a dotted model path, a Model class, or a dict"
                raise ValueError(msg)
        return result


def load_global_config() -> GlobalConfig:
    """Read ``settings.NINJA_POSTGREST`` and apply defaults."""
    raw: dict[str, Any] = getattr(settings, "NINJA_POSTGREST", {}) or {}
    return GlobalConfig(
        default_auth=raw.get("DEFAULT_AUTH", UNSET),
        default_permissions=raw.get("DEFAULT_PERMISSIONS", "guardian"),
        max_limit=raw.get("MAX_LIMIT", 1000),
        default_limit=raw.get("DEFAULT_LIMIT"),
        tables=raw.get("TABLES"),
    )


def resolve_auth(value: Any) -> Any:
    """Public wrapper around :func:`_resolve_auth` for per-table overrides."""
    return _resolve_auth(value)


_global_config: GlobalConfig | None = None


def get_global_config() -> GlobalConfig:
    """Return the (cached) global config."""
    global _global_config
    if _global_config is None:
        _global_config = load_global_config()
    return _global_config


def reset_global_config() -> None:
    global _global_config
    _global_config = None
