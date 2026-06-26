import os
from pathlib import Path

import dagster as dg
import pandas as pd
import pytest
import xarray as xr

from common import io, test_utils
from pipeline import HohonuDataset, defs_for_dataset

from hohonu_api import HohonuApi

pytest_plugins = ["common.test_utils.snapshot"]


TEST_DATA_DIR = Path("/mnt/test-data/hohonu/")


@pytest.fixture(scope="session")
def lazy_datadir() -> Path:
    return TEST_DATA_DIR


@pytest.fixture(scope="session")
def original_datadir() -> Path:
    return TEST_DATA_DIR


@pytest.fixture(scope="module")
def vcr_config():
    return {
        "filter_headers": [("Authorization", "FAKE")],
        "ignore_hosts": ["spotlight"],
    }


@pytest.fixture
def dataset():
    config_path = TEST_DATA_DIR / "fixtures/boothbay_dmr.json"
    return HohonuDataset.from_fixture(config_path, "2026-01-10T14:03:55.644Z")


@pytest.fixture
def defs(dataset):
    return defs_for_dataset(dataset)


def test_can_build_defs(defs):
    assert defs is not None
    assert len(defs.assets) == 3


@pytest.mark.vcr(TEST_DATA_DIR / "cassettes/test_hohonu_pipeline/test_daily_asset.yaml")
def test_daily_asset(defs, dataset, pandas_csv_regression):
    daily_df = test_utils.get_asset_by_name(defs, "daily_df")
    spec = daily_df.get_asset_spec()

    assert daily_df is not None, "There should be a daily_df asset"
    assert spec.group_name == "boothbay_dmr", "The group name should be boothbay_dmr"
    assert spec.description == "Download daily dataframe from Hohonu for boothbay_dmr"
    assert spec.metadata[io.DESIRED_PATH] == dataset.daily_csv_partition_path()

    context = dg.build_asset_context(partition_key="2025-09-30")

    api_key = os.environ.get("HOHONU_API_KEY", "FAKE")
    hohonu_api = HohonuApi(api_key=api_key)

    df = daily_df(context, hohonu_api=hohonu_api)

    assert isinstance(df, pd.DataFrame)

    pandas_csv_regression.check(df, basename="test_daily_asset")


def _get_monthly_ds(defs):
    monthly_ds = test_utils.get_asset_by_name(defs, "monthly_ds")
    context = dg.build_asset_context(partition_key="2025-09-01")

    daily_df = {
        "2025-09-01": pd.read_csv(
            TEST_DATA_DIR / "test_daily_asset.csv",
            parse_dates=["time"],
        ),
    }
    daily_df["2025-09-02"] = daily_df["2025-09-01"].copy()
    daily_df["2025-09-02"]["time"] += pd.Timedelta(days=1)

    ds = monthly_ds(context, daily_df=daily_df)

    return monthly_ds, context, ds


def test_monthly_nc_asset(defs, dataset, nc_io_regression):
    monthly_ds, context, ds = _get_monthly_ds(defs)
    assert monthly_ds is not None

    spec = monthly_ds.get_asset_spec()
    assert spec.group_name == "boothbay_dmr"
    assert spec.description == "Monthly NetCDFs for boothbay_dmr"
    assert spec.metadata[io.DESIRED_PATH] == dataset.monthly_nc_partition_path()

    assert isinstance(ds, xr.Dataset)
    assert "navd88_meters" in ds.data_vars, "The dataset should have a metric variable"
    assert (
        ds["navd88_meters"].attrs["standard_name"]
        == "sea_surface_height_above_geopotential_datum"
    ), "Attributes should be applied"

    nc_io_regression.check(ds, basename="test_monthly_asset", method="allclose")


def test_monthly_parquet_asset(defs, dataset):
    monthly_parquet = test_utils.get_asset_by_name(defs, "monthly_parquet")
    monthly_ds, context, ds = _get_monthly_ds(defs)

    spec = monthly_parquet.get_asset_spec()
    assert monthly_parquet is not None
    assert spec.group_name == "boothbay_dmr"
    assert spec.description == "Monthly parquet files for boothbay_dmr"
    assert spec.metadata[io.DESIRED_PATH] == dataset.monthly_parquet_partition_path()

    df = monthly_parquet(context, monthly_ds=ds)
    assert isinstance(df, pd.DataFrame)
    assert isinstance(ds, xr.Dataset)
    assert "navd88_meters" in df.columns
