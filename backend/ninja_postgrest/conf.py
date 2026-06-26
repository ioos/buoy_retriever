"""Loading and normalisation of the ``NINJA_POSTGREST`` setting."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from django.conf import settings
from django.utils.module_loading import import_string

# Sentinel distinguishing "not configured" from an explicit ``None`` (which, for
# auth, means "no authentication required").
UNSET = object()

VALID_PERMISSION_MODES = ("guardian", "model", "open")


def _resolve_auth(value: Any) -> Any:
    """Resolve an auth setting into something Django-Ninja accepts.

    Accepts an import-path string, a callable/instance, a list of either, or
    ``None``. Strings are imported; lists are resolved element-wise.
    """
    if value is None or value is UNSET:
        return value
    if isinstance(value, str):
        return import_string(value)
    if isinstance(value, (list, tuple)):
        return [_resolve_auth(item) for item in value]
    return value


@dataclass
class GlobalConfig:
    default_auth: Any = UNSET
    default_permissions: str = "guardian"
    max_limit: int = 1000
    default_limit: int | None = None
    tables: dict[str, Any] = field(default_factory=dict)


def load_global_config() -> GlobalConfig:
    """Read ``settings.NINJA_POSTGREST`` and apply defaults."""
    raw: dict[str, Any] = getattr(settings, "NINJA_POSTGREST", {}) or {}

    default_permissions = raw.get("DEFAULT_PERMISSIONS", "guardian")
    if default_permissions not in VALID_PERMISSION_MODES:
        msg = (
            f"NINJA_POSTGREST['DEFAULT_PERMISSIONS'] must be one of "
            f"{VALID_PERMISSION_MODES!r}, got {default_permissions!r}"
        )
        raise ValueError(msg)

    return GlobalConfig(
        default_auth=_resolve_auth(raw.get("DEFAULT_AUTH", UNSET)),
        default_permissions=default_permissions,
        max_limit=int(raw.get("MAX_LIMIT", 1000)),
        default_limit=raw.get("DEFAULT_LIMIT"),
        tables=raw.get("TABLES", {}) or {},
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
