from datetime import date
from pathlib import Path
from typing import Annotated

import dagster as dg
import pandas as pd
import xarray as xr
from pydantic import Field, ValidationError

from common import assets, config, io
from common.sentry import SentryConfig

from hohonu_api import HohonuApi

sentry = SentryConfig(pipeline_name="hohonu")


class HohonuConfig(
    config.DatasetConfigBase,
    # config.AttributeConfigMixin,
):
    """Configuration for Hohonu Dataset"""

    station: Annotated[str, Field(description="Station name/timeseries_id")]
    hohonu_id: Annotated[str, Field(description="Hohonu station ID")]
    start_date: date

    latitude: Annotated[
        float,
        Field(description="Fixed latitude of the station"),
    ]
    longitude: Annotated[
        float,
        Field(description="Fixed longitude of the station"),
    ]


class HohonuDataset(config.DatasetBase):
    """Hohonu Dataset"""

    config: Annotated[
        HohonuConfig,
        Field(description="The configuration for the dataset."),
    ]

    def daily_csv_partition_path(self):
        """Path to daily partitions"""
        return (
            self.safe_slug
            + "/daily/{partition_key_dt:%Y}/{partition_key_dt:%m}/{partition_key_dt:%Y-%m-%d}.csv"
        )

    def monthly_nc_partition_path(self):
        """Path to monthly partitions"""
        return (
            self.safe_slug
            # + "/monthly/{partition_key_dt:%Y}/"
            + "/monthly/nc/"
            + self.slug
            + "_{partition_key_dt:%Y-%m}.nc"
        )

    def monthly_parquet_partition_path(self):
        """Path to monthly partitions"""
        return (
            self.safe_slug
            + "/monthly/parquet/{partition_key_dt:%Y}/"
            + self.slug
            + "_{partition_key_dt:%Y-%m}.parquet"
        )


def defs_for_dataset(dataset: HohonuDataset) -> dg.Definitions:
    """Generate Dagster Definitions for a given dataset"""
    common_asset_kwargs = {
        "key_prefix": ["Hohonu", dataset.safe_slug],
        "group_name": dataset.safe_slug,
    }

    daily_partitions = dg.DailyPartitionsDefinition(
        start_date=dataset.config.start_date.isoformat(),
        end_offset=1,
    )
    monthly_partitions = dg.MonthlyPartitionsDefinition(
        start_date=dataset.config.start_date.strftime("%Y-%m-01"),
        end_offset=1,
    )

    @dg.asset(
        partitions_def=daily_partitions,
        description=f"Download daily dataframe from Hohonu for {dataset.slug}",
        metadata={io.DESIRED_PATH: dataset.daily_csv_partition_path()},
        **io.CSV_ASSET_KWARGS,
        **common_asset_kwargs,
    )
    @sentry.capture_op_exceptions
    def daily_df(
        context: dg.AssetExecutionContext,
        hohonu_api: HohonuApi,
    ) -> pd.DataFrame:
        """Fetch daily data from Hohonu API"""
        partition_date_string = context.asset_partition_key_for_output()

        try:
            daily_response = hohonu_api.load_daily_data(
                dataset.config.hohonu_id,
                partition_date_string,
            )
        except ValidationError as e:
            raise dg.Failure(f"No data available for {partition_date_string}") from e
        try:
            df = daily_response.to_df()
        except (IndexError, KeyError) as e:
            raise dg.Failure(f"No data available for {partition_date_string}") from e

        return df

    @dg.asset(
        description=f"Monthly NetCDFs for {dataset.slug}",
        ins={
            "daily_df": dg.AssetIn(
                partition_mapping=dg.TimeWindowPartitionMapping(
                    allow_nonexistent_upstream_partitions=True,
                ),
                metadata={io.ALLOW_MISSING_PARTITIONS: True},
            ),
        },
        automation_condition=assets.auto_condition_eager_allow_missing(),
        partitions_def=monthly_partitions,
        metadata={io.DESIRED_PATH: dataset.monthly_nc_partition_path()},
        **io.NETCDF_ASSET_KWARGS,
        **common_asset_kwargs,
    )
    @sentry.capture_op_exceptions
    def monthly_ds(
        context: dg.AssetExecutionContext,
        daily_df: dict[str, pd.DataFrame],
    ) -> xr.Dataset:
        """Generate monthly NetCDF from daily dataframes"""
        import pint

        ureg = pint.UnitRegistry()

        df = pd.concat(daily_df.values(), ignore_index=True)
        df = df.sort_values("time")
        df = df.drop_duplicates(subset=["time"])
        df["time"] = pd.to_datetime(df["time"])
        df = df.set_index("time")
        df = df.rename(
            columns={
                "observed": "navd88_feet",
                "forecast": "hohonu_forecast_navd88_feet",
            },
        )
        df["navd88_meters"] = (df["navd88_feet"].to_numpy() * ureg.feet).to(ureg.meter)

        ds = df.to_xarray()

        ds["station"] = dataset.config.station
        ds["latitude"] = dataset.config.latitude
        ds["longitude"] = dataset.config.longitude

        ds = ds.set_coords(["station", "latitude", "longitude"])

        common_attrs = config.NcAttributes.from_yaml(
            Path(__file__).parent / "attributes.yaml",
        )
        context.log.info(
            f"Applying attributes from {Path(__file__).parent / 'attributes.yaml'}: {common_attrs}",
        )
        common_attrs.apply_to_dataset(ds)

        ds["time"].encoding.update(
            {"units": "seconds since 1970-01-01T00:00:00Z", "calendar": "gregorian"},
        )

        return ds

    @dg.asset(
        description=f"Monthly parquet files for {dataset.slug}",
        automation_condition=assets.auto_condition_eager_allow_missing(),
        partitions_def=monthly_partitions,
        metadata={io.DESIRED_PATH: dataset.monthly_parquet_partition_path()},
        **io.PARQUET_ASSET_KWARGS,
        **common_asset_kwargs,
    )
    @sentry.capture_op_exceptions
    def monthly_parquet(
        context: dg.AssetExecutionContext,
        monthly_ds: xr.Dataset,
    ) -> pd.DataFrame:
        """Generate monthly parquet files from monthly xarray datasets (netcdf)"""
        return monthly_ds.to_dataframe()

    return dg.Definitions(assets=[daily_df, monthly_ds, monthly_parquet])
