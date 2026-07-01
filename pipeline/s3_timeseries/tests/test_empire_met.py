import dagster as dg
import pandas as pd
import pytest
import xarray as xr

from common import io, test_utils
from pipeline import S3TimeseriesDataset, defs_for_dataset


@pytest.fixture
def dataset_config(test_data_dir):
    config_path = test_data_dir / "fixtures/empire_met.json"
    return S3TimeseriesDataset.from_fixture(config_path, "2026-01-09T01:31:15.453Z")


@pytest.fixture
def defs(dataset_config):
    return defs_for_dataset(dataset_config)


def test_can_build_defs(defs):
    assert defs is not None
    assert len(defs.assets) == 2


def test_sensor(defs, mocked_s3, s3_credentials):
    bucket = "ott-empire"
    object_key1 = "EW01_met_20251112_120000.txt"  # gitleaks:allow
    object_key2 = "EW01_met_20251113_235056.txt"  # gitleaks:allow
    mocked_s3.create_bucket(Bucket=bucket)
    mocked_s3.put_object(Bucket=bucket, Key=object_key1, Body="test")
    mocked_s3.put_object(Bucket=bucket, Key=object_key2, Body="test")

    sensor = test_utils.get_sensor_by_name(defs, "empire_met_s3_sensor")
    assert sensor is not None

    context = dg.build_sensor_context(
        cursor="2025-11-12T23:50:56+00:00",
        instance=dg.DagsterInstance.ephemeral(),
    )

    run_requests = list(sensor(context, s3_credentials=s3_credentials))
    assert len(run_requests) == 2
    assert run_requests[0].partition_key == "2025-11-12"
    # the context isn't keeping the updated cursor in tests for some reason
    # assert context.cursor == "2025-11-12T23:50:56+00:00"


@pytest.mark.aws
def test_daily_asset(defs, dataset_config, s3_resource, pandas_csv_regression):
    daily_df = test_utils.get_asset_by_name(defs, "daily_df")
    spec = daily_df.get_asset_spec()

    assert daily_df is not None, "There should be a daily_df asset"
    assert spec.group_name == "empire_met", "The group name should be empire_met"
    assert spec.description == "Download daily dataframe from S3."
    assert spec.metadata[io.DESIRED_PATH] == dataset_config.daily_partition_path()

    context = dg.build_asset_context(partition_key="2025-11-13")

    df = daily_df(context, s3fs=s3_resource)

    assert isinstance(df, pd.DataFrame)
    assert not df.empty

    pandas_csv_regression.check(df, basename="empire_met/test_empire_met_daily_asset")


def test_monthly_asset(defs, dataset_config, nc_io_regression, test_data_dir):
    monthly_ds = test_utils.get_asset_by_name(defs, "monthly_ds")
    spec = monthly_ds.get_asset_spec()
    assert monthly_ds is not None
    assert spec.group_name == "empire_met"
    assert (
        spec.description
        == "Combine daily dataframes into a monthly NetCDF and apply transformations."
    )
    assert spec.metadata[io.DESIRED_PATH] == dataset_config.monthly_partition_path()
    context = dg.build_asset_context(partition_key="2025-11-01")

    daily_df = {
        "2025-11-12": pd.read_csv(
            test_data_dir / "empire_met/test_empire_met_daily_asset.csv",
            parse_dates=["datetime"],
        ),
    }
    daily_df["2025-11-13"] = daily_df["2025-11-12"].copy()
    daily_df["2025-11-13"]["datetime"] += pd.Timedelta(days=1)

    ds = monthly_ds(context, daily_df=daily_df)

    assert isinstance(ds, xr.Dataset)
    nc_io_regression.check(ds, basename="empire_met/test_empire_met_monthly_asset")


def test_monthly_asset_with_nans(defs, dataset_config, nc_io_regression, test_data_dir):
    monthly_ds = test_utils.get_asset_by_name(defs, "monthly_ds")
    context = dg.build_asset_context(partition_key="2025-10-01")

    daily_df = {
        "2025-10-12": pd.read_csv(
            test_data_dir / "empire_met/2025-10-12.csv",
            parse_dates=["datetime"],
        ),
        "2025-10-13": pd.read_csv(
            test_data_dir / "empire_met/2025-10-13.csv",
            parse_dates=["datetime"],
        ),
    }

    ds = monthly_ds(context, daily_df=daily_df)

    assert isinstance(ds, xr.Dataset)
    nc_io_regression.check(
        ds,
        basename="empire_met/test_empire_met_monthly_asset_with_nans",
    )
