from datetime import datetime
from pathlib import Path

import pytest

from common.config import ConfigState, DatasetBase, DatasetConfigBase


class DatasetTestConfig(DatasetConfigBase):
    """Test Dataset Config"""

    test_field: str


class DatasetTest(DatasetBase):
    """Test Dataset"""

    config: DatasetTestConfig


def test_dataset_config():
    """Test DatasetConfigBase"""
    config = DatasetTestConfig(test_field="test")
    assert config.test_field == "test"
    assert config.model_dump() == {"test_field": "test"}


def test_dataset_config_schema():
    """Test DatasetConfigBase JSON Schema"""
    assert DatasetTestConfig.model_json_schema() == {
        "title": "DatasetTestConfig",
        "type": "object",
        "properties": {
            "test_field": {"title": "Test Field", "type": "string"},
        },
        "required": ["test_field"],
        "description": "Test Dataset Config",
    }


def test_dataset():
    dataset = DatasetTest(
        slug="test-dataset",
        config=DatasetTestConfig(test_field="test"),
        created="2026-11-09T00:00:00.000Z",
        edited="2026-11-09T00:00:00.000Z",
    )
    assert dataset.slug == "test-dataset"
    assert dataset.safe_slug == "test_dataset"
    assert dataset.config.test_field == "test"
    assert dataset.model_dump() == {
        "slug": "test-dataset",
        "config": {"test_field": "test"},
        "config_state": ConfigState.DRAFT,
        "created": datetime.fromisoformat("2026-11-09T00:00:00.000Z"),
        "edited": datetime.fromisoformat("2026-11-09T00:00:00.000Z"),
    }


class LoadableTestDataset(DatasetBase):
    """A dataset class that can be loaded from a fixture"""

    config: DatasetConfigBase


def test_dataset_from_fixture():
    path = (
        Path(__file__).parent.parent.parent.parent
        / "docker-data/test-data/s3_timeseries/fixtures/empire_met.json"
    )
    created_dt_str = "2026-01-05T21:15:24.530Z"
    dataset = LoadableTestDataset.from_fixture(path, created_dt_str)
    assert dataset.slug == "empire_met"
    assert dataset.config_state == ConfigState.DRAFT


def test_dataset_from_fixture_approximate_timestamp():
    path = (
        Path(__file__).parent.parent.parent.parent
        / "docker-data/test-data/s3_timeseries/fixtures/empire_met.json"
    )
    created_dt_str = "2026-01-05T21:15:24.000Z"  # slightly different timestamp
    dataset = LoadableTestDataset.from_fixture(path, created_dt_str)
    assert dataset.slug == "empire_met"
    assert dataset.config_state == ConfigState.DRAFT


def test_dataset_from_fixture_invalid_timestamp():
    path = (
        Path(__file__).parent.parent.parent.parent
        / "docker-data/test-data/s3_timeseries/fixtures/empire_met.json"
    )
    created_dt_str = "2026-01-01T01:00:00.000Z"
    with pytest.raises(ValueError) as e:
        LoadableTestDataset.from_fixture(path, created_dt_str)
    assert (
        str(e.value)
        == f"No dataset config found in fixture {path} with created datetime {created_dt_str}"
    )
