import os
from pathlib import Path

import boto3
import dagster as dg
import pandas as pd
import pytest
import xarray as xr
from moto import mock_aws

from common import io, test_utils
from common.resource.s3fs_resource import S3Credentials, S3FSResource
from pipeline import S3TimeseriesDataset, defs_for_dataset

TEST_DATA_DIR = Path("/mnt/test-data/s3_timeseries/")


@pytest.fixture
def dataset_config(asset_name, created_dt_str):
    config_path = TEST_DATA_DIR / f"fixtures/{asset_name}.json"
    return S3TimeseriesDataset.from_fixture(config_path, created_dt_str)


@pytest.fixture
def defs(dataset_config):
    return defs_for_dataset(dataset_config)


@pytest.mark.parametrize(
    "asset_name,created_dt_str",
    [
        pytest.param("empire_met", "2026-01-05T21:15:24.482Z"),
    ],
)
def test_can_build_defs(defs):
    assert defs is not None
    assert len(defs.assets) == 2


@pytest.fixture
def s3_credentials():
    return S3Credentials(
        access_key_id=os.environ["S3_TS_ACCESS_KEY_ID"],
        secret_access_key=os.environ["S3_TS_SECRET_ACCESS_KEY"],
    )


@pytest.fixture
def s3_resource(s3_credentials):
    return S3FSResource(
        credentials=s3_credentials,
        region_name="us-east-1",
    )


@pytest.fixture
def mocked_s3():
    with mock_aws():
        yield boto3.client("s3", region_name="us-east-1")


@pytest.mark.parametrize(
    "asset_name,created_dt_str,bucket,object_key1,object_key2,selected_date,partition_key",
    [
        pytest.param(
            "empire_met",
            "2026-01-05T21:15:24.482Z",
            "ott-empire",
            "EW01_met_20251112_000500_002000.txt",
            "EW01_met_20251113_235500_010000.txt",
            "2025-11-12T23:50:56+00:00",
            "2025-11-12",
        ),
        pytest.param(
            "empire_waves",
            "2026-04-08T19:34:39.383Z",
            "ott-empire",
            "EW01_wave_ioos_20260122_233557_233557.txt",
            "EW01_wave_ioos_20260123_023557_023557.txt",
            "2026-01-23T03:30:24+00:00",
            "2026-01-22",
        ),
    ],
)
def test_sensor(
    defs,
    mocked_s3,
    s3_credentials,
    asset_name,
    bucket,
    object_key1,
    object_key2,
    selected_date,
    partition_key,
):
    mocked_s3.create_bucket(Bucket=bucket)
    mocked_s3.put_object(Bucket=bucket, Key=object_key1, Body="test")
    mocked_s3.put_object(Bucket=bucket, Key=object_key2, Body="test")

    sensor = test_utils.get_sensor_by_name(defs, f"{asset_name}_s3_sensor")

    assert sensor is not None

    context = dg.build_sensor_context(
        cursor=selected_date,
        instance=dg.DagsterInstance.ephemeral(),
    )

    run_requests = list(sensor(context, s3_credentials=s3_credentials))
    assert len(run_requests) == 2
    assert run_requests[0].partition_key == partition_key


@pytest.mark.parametrize(
    "asset_name,created_dt_str,snapshot_path,partition_key",
    [
        pytest.param(
            "empire_met",
            "2026-01-05T21:15:24.530Z",
            TEST_DATA_DIR / "empire_met/test_empire_met_20251113.csv",
            "2025-11-13",
        ),
        pytest.param(
            "empire_waves",
            "2026-04-08T19:34:39.383Z",
            TEST_DATA_DIR / "empire_waves/test_empire_waves_20251112.csv",
            "2025-11-12",
        ),
        pytest.param(
            "empire_ctd",
            "2026-04-08T19:34:01.989Z",
            TEST_DATA_DIR / "empire_ctd/test_empire_ctd_20251208.csv",
            "2025-12-08",
        ),
        pytest.param(
            "empire_adcp_water",
            "2026-04-08T19:33:23.624Z",
            TEST_DATA_DIR / "empire_adcp_water/test_empire_adcp_water_20251028.csv",
            "2025-10-28",
        ),
        pytest.param(
            "empire_adcp_currents",
            "2026-04-08T19:32:26.472Z",
            TEST_DATA_DIR
            / "empire_adcp_currents/test_empire_adcp_currents_20251030.csv",
            "2025-10-30",
        ),
        pytest.param(
            "south_fork_currents",
            "2026-04-08T19:35:09.835Z",
            TEST_DATA_DIR / "south_fork_currents/test_south_fork_currents_20260304.csv",
            "2026-03-04",
        ),
        pytest.param(
            "south_fork_waves",
            "2026-04-08T19:36:09.281Z",
            TEST_DATA_DIR / "south_fork_waves/test_south_fork_waves_20260221.csv",
            "2026-02-21",
        ),
        pytest.param(
            "south_fork_water",
            "2026-04-08T19:35:35.695Z",
            TEST_DATA_DIR / "south_fork_water/test_south_fork_water_20260122.csv",
            "2026-01-22",
        ),
        pytest.param(
            "cvow",
            "2026-04-08T19:31:35.891Z",
            TEST_DATA_DIR / "cvow/test_cvow_daily_asset.csv",
            "2025-12-22",
        ),
    ],
)
@pytest.mark.aws
def test_daily_asset(
    defs,
    dataset_config,
    s3_resource,
    asset_name,
    snapshot_path,
    partition_key,
):
    daily_df = test_utils.get_asset_by_name(defs, "daily_df")
    spec = daily_df.get_asset_spec()

    assert daily_df is not None, "There should be a daily_df asset"
    assert spec.group_name == asset_name, f"The group name should be {asset_name}"
    assert spec.description == "Download daily dataframe from S3."
    assert spec.metadata[io.DESIRED_PATH] == dataset_config.daily_partition_path()

    context = dg.build_asset_context(partition_key=partition_key)

    df = daily_df(context, s3fs=s3_resource)

    assert isinstance(df, pd.DataFrame)
    assert not df.empty

    # Uncomment to update CSV snapshot
    # df.to_csv(snapshot_path, index=False)

    snapshot = pd.read_csv(
        snapshot_path,
    )

    snapshot[dataset_config.config.source_time_var] = pd.to_datetime(
        df[dataset_config.config.source_time_var],
    )

    pd.testing.assert_frame_equal(df, snapshot)


@pytest.mark.parametrize(
    "asset_name,created_dt_str,daily_snapshot_dict,monthly_snapshot_path,monthly_partition_key",
    [
        pytest.param(
            "empire_met",
            "2026-01-05T21:15:24.530Z",
            {
                "2025-11-13": TEST_DATA_DIR / "empire_met/test_empire_met_20251113.csv",
                "2025-11-14": TEST_DATA_DIR / "empire_met/test_empire_met_20251114.csv",
            },
            TEST_DATA_DIR / "empire_met/test_empire_met_202511.nc",
            "2025-11-01",
        ),
        pytest.param(
            "empire_met",
            "2026-01-05T21:15:24.530Z",
            {
                "2025-10-12": TEST_DATA_DIR / "empire_met/2025-10-12.csv",
                "2025-10-13": TEST_DATA_DIR / "empire_met/2025-10-13.csv",
            },
            TEST_DATA_DIR / "empire_met/test_empire_met_202510_nans.nc",
            "2025-12-01",
        ),
        pytest.param(
            "empire_waves",
            "2026-04-08T19:34:39.383Z",
            {
                "2025-11-12": TEST_DATA_DIR
                / "empire_waves/test_empire_waves_20251112.csv",
            },
            TEST_DATA_DIR / "empire_waves/test_empire_waves_202511.nc",
            "2025-11-01",
        ),
        pytest.param(
            "empire_ctd",
            "2026-04-08T19:34:01.989Z",
            {
                "2025-12-08": TEST_DATA_DIR / "empire_ctd/test_empire_ctd_20251208.csv",
                "2025-12-09": TEST_DATA_DIR / "empire_ctd/test_empire_ctd_20251209.csv",
            },
            TEST_DATA_DIR / "empire_ctd/test_empire_ctd_202512.nc",
            "2025-12-01",
        ),
        pytest.param(
            "empire_adcp_water",
            "2026-04-08T19:33:23.624Z",
            {
                "2025-10-28": TEST_DATA_DIR
                / "empire_adcp_water/test_empire_adcp_water_20251028.csv",
            },
            TEST_DATA_DIR / "empire_adcp_water/test_empire_adcp_water_202510.nc",
            "2025-10-01",
        ),
        pytest.param(
            "empire_adcp_currents",
            "2026-04-08T19:32:26.472Z",
            {
                "2025-10-30": TEST_DATA_DIR
                / "empire_adcp_currents/test_empire_adcp_currents_20251030.csv",
            },
            TEST_DATA_DIR / "empire_adcp_currents/test_empire_adcp_currents_202510.nc",
            "2025-10-01",
        ),
        pytest.param(
            "south_fork_currents",
            "2026-04-08T19:35:09.835Z",
            {
                "2026-03-04": TEST_DATA_DIR
                / "south_fork_currents/test_south_fork_currents_20260304.csv",
            },
            TEST_DATA_DIR / "south_fork_currents/test_south_fork_currents_202603.nc",
            "2026-03-01",
        ),
        pytest.param(
            "south_fork_waves",
            "2026-04-08T19:36:09.281Z",
            {
                "2026-02-21": TEST_DATA_DIR
                / "south_fork_waves/test_south_fork_waves_20260221.csv",
            },
            TEST_DATA_DIR / "south_fork_waves/test_south_fork_waves_202602.nc",
            "2026-02-01",
        ),
        pytest.param(
            "south_fork_water",
            "2026-04-08T19:35:35.695Z",
            {
                "2026-01-22": TEST_DATA_DIR
                / "south_fork_water/test_south_fork_water_20260122.csv",
            },
            TEST_DATA_DIR / "south_fork_water/test_south_fork_water_202601.nc",
            "2026-01-01",
        ),
        pytest.param(
            "cvow",
            "2026-04-08T19:31:35.891Z",
            {
                "2025-12-22": TEST_DATA_DIR / "cvow/test_cvow_20251222.csv",
            },
            TEST_DATA_DIR / "cvow/test_cvow_202512.nc",
            "2025-12-01",
        ),
    ],
)
def test_monthly_asset(
    defs,
    dataset_config,
    asset_name,
    daily_snapshot_dict,
    monthly_snapshot_path,
    monthly_partition_key,
):
    monthly_ds = test_utils.get_asset_by_name(defs, "monthly_ds")
    spec = monthly_ds.get_asset_spec()
    assert monthly_ds is not None
    assert spec.group_name == f"{asset_name}"
    assert (
        spec.description
        == "Combine daily dataframes into a monthly NetCDF and apply transformations."
    )
    assert spec.metadata[io.DESIRED_PATH] == dataset_config.monthly_partition_path()
    context = dg.build_asset_context(partition_key=monthly_partition_key)

    daily_df = {}

    for daily_key in daily_snapshot_dict:
        daily_df[daily_key] = pd.read_csv(
            daily_snapshot_dict[daily_key],
            parse_dates=[dataset_config.config.source_time_var],
        )

    ds = monthly_ds(context, daily_df=daily_df)

    assert isinstance(ds, xr.Dataset)

    # Uncomment to update monthly NetCDF snapshot
    # ds.to_netcdf(monthly_snapshot_path)

    snapshot = xr.load_dataset(monthly_snapshot_path, decode_timedelta=False)

    xr.testing.assert_equal(ds, snapshot)
