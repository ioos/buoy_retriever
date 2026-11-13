import pytest
from dagster import AssetKey

from common.dagster_api import coerce_asset_keys


def test_bare_asset_key_is_rejected():
    with pytest.raises(TypeError):
        coerce_asset_keys(AssetKey(["Hohonu", "station", "daily_df"]))


def test_multi_part_paths_stay_single_keys():
    assert coerce_asset_keys([["Hohonu", "station", "daily_df"]]) == [
        AssetKey(["Hohonu", "station", "daily_df"]),
    ]


def test_mixed_coercible_keys():
    key = AssetKey(["a", "b"])
    assert coerce_asset_keys([key, "single", ["multi", "part"]]) == [
        key,
        AssetKey("single"),
        AssetKey(["multi", "part"]),
    ]


def test_flat_strings_are_single_part_keys():
    assert coerce_asset_keys(["a", "b"]) == [AssetKey("a"), AssetKey("b")]


def test_bare_string_is_rejected():
    with pytest.raises(TypeError):
        coerce_asset_keys("Hohonu")
