"""Load and save NetCDFs with Xarray to datastore"""

from pathlib import Path

import xarray as xr
from dagster import InputContext, MetadataValue, OutputContext

from .base import IOManagerBase


class XarrayNcIoManager(IOManagerBase):
    """Load and save NetCDFs with Xarray"""

    def dump_to_path(self, context: OutputContext, obj: xr.Dataset, path: Path) -> None:
        """Save Dataset to given path as a NetCDF"""
        try:
            obj.to_netcdf(path)
        except (ValueError, TypeError) as e:
            raise TypeError(f"Failed to save {path} as NetCDF. {obj}") from e

        context.add_output_metadata({"nc.meta": MetadataValue.md(f"```\n{obj}\n```")})

    def load_from_path(self, context: InputContext, path: Path):
        """Load a dataset from a given path"""
        with xr.open_dataset(path, decode_timedelta=False) as ds:
            return ds
