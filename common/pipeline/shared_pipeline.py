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


def monthly_pipeline_ds(
    context: dg.AssetExecutionContext,
    daily_df: dict[str, pd.DataFrame],
    dataset: BaseTimeseriesConfig,
    na_values: None | str | list[str] = None,
) -> xr.Dataset:
    """Combine daily dataframes into a monthly NetCDF and apply transformations."""

    daily_dfs = []

    for df_date, df in daily_df.items():
        for var_map in dataset.config.variable_mappings:
            if var_map.source in df.columns:
                df = df.rename(columns={var_map.source: var_map.output})
            else:
                context.log.warning(
                    f"Source variable '{var_map.source}' not found in data for {df_date}",
                )

        if len(set(df.columns)) != len(df.columns):
            context.log.warning(
                f"Column name collision after renaming for data on {df_date}, trying to squish duplicates",
            )
            df = df.groupby(df.columns, axis=1).first()

            # Avoid attempting to convert the time column to numeric inside
            # clean_up_dtypes_and_nas, which causes unnecessary exceptions.
        if "time" in df.columns:
            time_col = df["time"]
            df_wo_time = df.drop(columns=["time"])
            print(f"df_wo_time {df_wo_time}")
            df_wo_time = clean_up_dtypes_and_nas(
                df_wo_time,
                na_values=na_values,
                logger=context.log,
            )
            df_wo_time["time"] = time_col
            df = df_wo_time
        else:
            df = clean_up_dtypes_and_nas(df, na_values=na_values, logger=context.log)
        daily_dfs.append(df)

    df = pd.concat(daily_dfs, ignore_index=True)

    if dataset.config.dataset_type == "profile":
        indx_var = ["time", "depth"]
    else:
        indx_var = "time"

    df = df.sort_values(indx_var)
    df = df.drop_duplicates(subset=indx_var)
    df["time"] = pd.to_datetime(df["time"])
    df = df.set_index(indx_var)

    ds = df.to_xarray()

    ds["station"] = dataset.config.station
    if dataset.config.latitude is not None:
        ds["latitude"] = dataset.config.latitude
    if dataset.config.longitude is not None:
        ds["longitude"] = dataset.config.longitude

    ds = ds.set_coords(["station", "latitude", "longitude"])

    # apply attributes

    ds["time"].encoding.update(
        {
            "units": "seconds since 1970-01-01T00:00:00Z",
            "calendar": "gregorian",
            "standard_name": "time",
        },
    )

    dataset.config.attributes.add_attributes_from_yaml()

    dataset.config.attributes.apply_to_dataset(ds)
    context.log.info(ds)
    return ds


def clean_up_dtypes_and_nas(
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
