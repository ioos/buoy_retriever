import json
import os
from pathlib import Path

import dagster as dg
import pandas as pd
import pytest
import xarray as xr

from common import io, test_utils
from common.resource.aveva_resource import AvevaCredentials, AvevaResource
from pipeline import AvevaTimeseriesDataset, defs_for_dataset


@pytest.fixture
def dataset_config(asset_name):
    with Path.open(f"/mnt/datasets_config/{asset_name}.json") as config_f:
        config = json.load(config_f)
    return AvevaTimeseriesDataset(
        slug=f"{asset_name}-test",
        config=config,
    )


@pytest.fixture
def defs(dataset_config):
    return defs_for_dataset(dataset_config)


@pytest.fixture
def aveva_credentials():
    print(f"client_id={os.environ['AVEVA_CLIENT_ID']}")
    return AvevaCredentials(
        client_id=os.environ["AVEVA_CLIENT_ID"],
        client_secret=os.environ["AVEVA_CLIENT_SECRET"],
    )


@pytest.fixture
def aveva_resource(aveva_credentials):
    return AvevaResource(
        credentials=aveva_credentials,
        ocs_resource="https://uswe.datahub.connect.aveva.com",
    )


@pytest.mark.parametrize(
    "asset_name",
    [
        pytest.param("aveva_test"),
    ],
)
def test_can_build_defs(defs):
    assert defs is not None
    assert len(defs.assets) == 2


@pytest.mark.parametrize(
    "asset_name,snapshot_path,partition_key",
    [
        pytest.param(
            "aveva_test",
            "tests/test_data/test_aveva_20260302.csv",
            "2026-03-02",
        ),
    ],
)
def test_daily_asset(
    defs,
    dataset_config,
    aveva_resource,
    asset_name,
    snapshot_path,
    partition_key,
):
    daily_df = test_utils.get_asset_by_name(defs, "daily_df")

    assert daily_df is not None, "There should be a daily_df asset"

    context = dg.build_asset_context(partition_key=partition_key)

    df = daily_df(context, aveva_resource=aveva_resource)

    assert isinstance(df, pd.DataFrame)
    assert not df.empty

    # Uncomment to update CSV snapshot
    snapshot = pd.read_csv(
        snapshot_path,
    )

    snapshot["time"] = pd.to_datetime(
        df["time"],
    )
    print(f"DF {df}")
    print(f"snapshot {snapshot}")
    print(f"DF {df.info()}")
    print(f"Snap {snapshot.info()}")
    pd.testing.assert_frame_equal(df, snapshot)


@pytest.mark.parametrize(
    "asset_name,daily_snapshot_dict,monthly_snapshot_path,monthly_partition_key",
    [
        pytest.param(
            "aveva_test",
            {
                "2026-03-02": "tests/test_data/test_aveva_20260302.csv",
            },
            "tests/test_data/empire_met/test_empire_met_202511.nc",
            "2026-03-01",
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
    assert spec.group_name == f"{asset_name}_test"
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
            parse_dates=["time"],
        )

    ds = monthly_ds(context, daily_df=daily_df)

    assert isinstance(ds, xr.Dataset)


#    snapshot = xr.load_dataset(monthly_snapshot_path, decode_timedelta=False)

#    xr.testing.assert_equal(ds, snapshot)
