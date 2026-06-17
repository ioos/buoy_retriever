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
    daily_dfs: list[pd.DataFrame],
    dataset: BaseTimeseriesConfig,
) -> xr.Dataset:
    """Combine daily dataframes into a monthly NetCDF and apply transformations."""

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
