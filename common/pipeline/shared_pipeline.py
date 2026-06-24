import logging
from datetime import date
from typing import Annotated

import dagster as dg
import pandas as pd
import xarray as xr
from pydantic import Field

from common import config
from common.config import attributes, mappings


class BaseTimeseriesConfig(
    config.DatasetConfigBase,
    # config.AttributeConfigMixin,
    mappings.VariableMappingMixin,
    attributes.AttributeConfigMixin,
    mappings.VariableConverterMixIn,
):
    """Configuration for Timeseries Dataset."""

    start_date: date

    dataset_type: Annotated[
        str,
        Field(description="Dateset type (timeseries or profile)"),
    ] = "timeseries"

    latitude: Annotated[
        float | None,
        Field(description="Fixed latitude of the station"),
    ] = None
    longitude: Annotated[
        float | None,
        Field(description="Fixed longitude of the station"),
    ] = None
    station: Annotated[str, Field(description="Station name/timeseries_id")]

    def with_coordinates(
        self,
        context: dg.AssetExecutionContext,
        ds: xr.Dataset,
    ) -> xr.Dataset:
        "Set station, latitude, and longitude coordinates"
        ds = ds.copy()
        ds["station"] = self.station
        if self.latitude is not None:
            ds["latitude"] = self.latitude
        if self.longitude is not None:
            ds["longitude"] = self.longitude

        ds = ds.set_coords(["station", "latitude", "longitude"])
        return ds

    def sort_and_index(self, df: pd.DataFrame) -> pd.DataFrame:
        """Sort, dedupe, make datetimes, set index"""
        df = df.copy()
        if self.dataset_type == "profile":
            indx_var = ["time", "depth"]
        else:
            indx_var = "time"

        df = df.sort_values(indx_var)
        df = df.drop_duplicates(subset=indx_var)
        df["time"] = pd.to_datetime(df["time"])
        df = df.set_index(indx_var)
        return df

    def cleanup_df(
        self,
        context: dg.AssetExecutionContext,
        daily_df: dict[str, pd.DataFrame],
        na_values: None | str | list[str],
    ) -> list[pd.DataFrame]:
        daily_dfs = []

        for df in daily_df.values():
            df = self.map_output(df)

            time_col = None

            # Avoid attempting to convert the time column to numeric inside
            # clean_up_dtypes_and_nas, which causes unnecessary exceptions.
            if "time" in df.columns:
                time_col = df["time"]
                df = df.drop(columns=["time"])

            df = self.clean_up_dtypes_and_nas(
                df,
                na_values=na_values,
                logger=context.log,
            )

            if time_col is not None:
                df["time"] = time_col

            daily_dfs.append(df)
        return daily_dfs

    def monthly_pipeline_ds(
        self,
        context: dg.AssetExecutionContext,
        daily_df: dict[str, pd.DataFrame],
        na_values: None | str | list[str] = None,
    ) -> xr.Dataset:
        """Combine daily dataframes into a monthly NetCDF and apply transformations."""

        daily_dfs = self.cleanup_df(context, daily_df, na_values)

        df = pd.concat(daily_dfs, ignore_index=True)

        df = self.sort_and_index(df)

        ds = df.to_xarray()

        ds = self.with_coordinates(context, ds)

        # apply attributes

        ds["time"].encoding.update(
            {
                "units": "seconds since 1970-01-01T00:00:00Z",
                "calendar": "gregorian",
                "standard_name": "time",
            },
        )

        self.attributes.add_attributes_from_yaml()

        self.attributes.apply_to_dataset(ds)
        context.log.info(ds)
        return ds

    def clean_up_dtypes_and_nas(
        self,
        df: pd.DataFrame,
        na_values: None | str | list[str] = None,
        logger: logging.Logger | None = None,
    ) -> pd.DataFrame:
        """Clean up data types and NA values in a dataframe"""
        df = df.copy()
        if not logger:
            logger = logging.getLogger(__name__)
        if na_values is not None:
            df = df.replace(na_values, pd.NA).dropna()

        for c in df.columns:
            try:
                df[c] = pd.to_numeric(df[c])
            except (ValueError, TypeError) as e:
                if logger:
                    logger.warning(f"Could not convert column {c} to numeric: {e}")

        return df
