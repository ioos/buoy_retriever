"""Tests for invalid NINJA_POSTGREST configuration.

Validation happens in two layers:
- Structural (Pydantic): caught when GlobalConfig / TableInputConfig is instantiated.
- Model-dependent (registry): caught when _build_table_config resolves field names
  against the actual Django model.
"""

import pytest
from django.test import override_settings
from pydantic import ValidationError

from ninja_postgrest.conf import GlobalConfig, TableInputConfig, reset_global_config
from ninja_postgrest.registry import build_registry, reset_registry


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _reset_caches():
    """Clear cached config/registry before and after each test."""
    reset_global_config()
    reset_registry()
    yield
    reset_global_config()
    reset_registry()


# --------------------------------------------------------------------------- #
# GlobalConfig — structural validation
# --------------------------------------------------------------------------- #
def test_invalid_default_permissions_rejected():
    with pytest.raises(ValidationError, match="default_permissions"):
        GlobalConfig(default_permissions="superuser")


def test_invalid_max_limit_rejected():
    with pytest.raises(ValidationError, match="max_limit"):
        GlobalConfig(max_limit="not-a-number")


def test_invalid_table_entry_type_rejected():
    # A bare integer is not a model path, Model class, or dict.
    with pytest.raises(ValidationError, match="must be a dotted model path"):
        GlobalConfig(tables={"mytable": 42})


# --------------------------------------------------------------------------- #
# TableInputConfig — structural validation
# --------------------------------------------------------------------------- #
def test_invalid_operation_rejected():
    with pytest.raises(ValidationError, match="operations"):
        TableInputConfig(model="datasets.Dataset", operations=["list", "patch"])


def test_invalid_table_permissions_rejected():
    with pytest.raises(ValidationError, match="permissions"):
        TableInputConfig(model="datasets.Dataset", permissions="superuser")


# --------------------------------------------------------------------------- #
# Registry — model-dependent validation
# --------------------------------------------------------------------------- #
@pytest.mark.django_db
def test_unknown_field_name_rejected():
    overridden = {
        "TABLES": {
            "datasets": {
                "model": "datasets.Dataset",
                "fields": ["slug", "nonexistent"],
            },
        },
    }
    with override_settings(NINJA_POSTGREST=overridden):
        reset_global_config()
        with pytest.raises(ValueError, match="nonexistent"):
            build_registry()


@pytest.mark.django_db
def test_unknown_embeddable_rejected():
    overridden = {
        "TABLES": {
            "datasets": {"model": "datasets.Dataset", "embeddable": ["not_a_relation"]},
        },
    }
    with override_settings(NINJA_POSTGREST=overridden):
        reset_global_config()
        with pytest.raises(ValueError, match="not_a_relation"):
            build_registry()
