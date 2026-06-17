import dagster as dg
import requests
import xarray as xr

from ..config.env import ERDDAPPER_TIMEOUT, ERDDAPPER_URL
from ..ncojson import convert_numpy_values


def reload_erddap_dataset(
    context: dg.AssetExecutionContext,
    pipeline: str,
    dataset_slug: str,
    dataset_safe_slug: str,
    monthly_ds: xr.Dataset,
) -> None:
    if not ERDDAPPER_URL:
        context.log.info(
            f"Skipping ERDDAP reload for {pipeline} {dataset_slug} because ERDDAPPER_URL is not set.",
        )
        return

    context.log.info(f"Reloading ERDDAP dataset for {pipeline} {dataset_slug}.")

    """Create or reload a dataset in ERDDAP via erddapper"""
    # use ncojson from monthly_ds attributes
    ncojson = {"attributes": monthly_ds.attrs}

    ncojson["variables"] = {
        var: {
            "type": get_erddap_var_type(var, monthly_ds.variables[var]),
            "attributes": monthly_ds.variables[var].attrs,
        }
        for var in monthly_ds.variables
    }

    # set erddapper config
    ncojson |= {
        "source_name": "ncojson-inline",
        "file_type": "nc",
        "config": {
            "fileDir": f"/data/datasets/{pipeline}/{dataset_safe_slug}",
        },
    }
    ncojson["attributes"] |= {
        "id": dataset_slug,
        "cdm_data_type": "TimeSeries",
        "defaultDataQuery": None,
    }

    ncojson = convert_numpy_values(ncojson)

    # tell erddapper to serve the dataset with the provided ncojson config
    try:
        response = requests.post(
            f"{ERDDAPPER_URL}/datasets/{dataset_slug}",
            json=ncojson,
            timeout=ERDDAPPER_TIMEOUT,
        )
        response.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise RuntimeError(
            f"erddapper request failed with message {response.text}",
        ) from e

    context.log.info(
        f"Reloaded ERDDAP dataset for {pipeline} {dataset_slug}. "
        f"ERDDAP dataset ID: {response.json()['erddap_dataset_id']}",
    )


def get_erddap_var_type(var_name: str, var: xr.Variable) -> str:
    """Map xarray dtype to ERDDAP type."""
    # TODO handle in erddapper?
    if var.dtype.kind in ["S", "T", "U"]:
        return "String"
    try:
        return {
            "float32": "float",
            "float64": "double",
            "int8": "byte",
            "int16": "short",
            "int32": "int",
            "int64": "long",
            "uint8": "ubyte",
            "uint16": "ushort",
            "uint32": "uint",
            "uint64": "ulong",
            "bool": "boolean",
            "datetime64[ns]": "int64",
        }[var.dtype.name]
    except KeyError as e:
        raise ValueError(
            f"Unhandled dtype {var.dtype.name} (kind {var.dtype.kind}) for variable {var_name}",
        ) from e
