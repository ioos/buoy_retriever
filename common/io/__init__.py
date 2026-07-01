"""Shared Dagster asset based IO managers, to allow us to reduce the amount that
we have to ponder saving and loading data.
"""

from pathlib import Path

import dagster as dg

# from ..resources.s3fs_resource import S3FSResource
from .csv_io import PandasCsvIoManager
from .datastore import Datastore
from .json_io import JsonIOManager
from .nc_io import XarrayNcIoManager
from .parquet_io import PandasParquetIoManager
from .tags import (
    ALLOW_MISSING_PARTITIONS,  # noqa: F401
    DESIRED_PATH,  # noqa: F401
    OUTPUT_PATH,  # noqa: F401
    S3_DESIRED_PATH,  # noqa: F401
    S3_OUTPUT_PATH,  # noqa: F401
    S3_PUBLIC,  # noqa: F401
    S3_URL,  # noqa: F401
)

CSV_KEY = "csv_io"
JSON_KEY = "json_io"
NETCDF_KEY = "netcdf_io"
PARQUET_KEY = "parquet_io"

CSV_ASSET_KWARGS = {
    "io_manager_key": CSV_KEY,
    "compute_kind": "pandas",
    "tags": {"dagster/storage_kind": "csv"},
}

JSON_ASSET_KWARGS = {
    "io_manager_key": JSON_KEY,
    "tags": {"dagster/storage_kind": "json"},
}

NETCDF_ASSET_KWARGS = {
    "io_manager_key": NETCDF_KEY,
    "compute_kind": "xarray",
    "tags": {"dagster/storage_kind": "NetCDF"},
}

PARQUET_ASSET_KWARGS = {
    "io_manager_key": PARQUET_KEY,
    "compute_kind": "pandas",
    "tags": {"dagster/storage_kind": "parquet"},
}

# MetOcean OSO development public bucket
OSO_DEV_BUCKET = "ioos-ott-oso-dev-public"


# def default_io_s3_resource() -> S3FSResource:
#     """
#     Create a S3FSResource with credentials from environment variables for datastore access.
#     """
#     from ..resources.s3fs_resource import S3Credentials, S3FSResource

#     s3_credentials = S3Credentials(
#         access_key_id=dg.EnvVar("DATASTORE_S3_AWS_ACCESS_KEY_ID"),
#         secret_access_key=dg.EnvVar("DATASTORE_S3_AWS_SECRET_ACCESS_KEY"),
#     )
#     s3 = S3FSResource(
#         credentials=s3_credentials,
#         region_name=dg.EnvVar("DATASTORE_S3_REGION_NAME"),
#     )
#     return s3


def common_resources(
    path_stub: str,
    datastore: Datastore | None = None,
    # s3: Optional[S3FSResource] = None,
    sync_to_s3_bucket: str | None = None,
    s3_default_access: bool = False,
) -> tuple[Datastore, dict[str, dg.ConfigurableResource]]:
    """Return Datastore and a dictionary of common IO Managers.

    Args:
        path_stub: The path stub to use for the datastore.
        datastore: The datastore to use. If None, a new one will be created.
        s3: The S3FSResource to use. If None, a new one will be created if needed.
        sync_to_s3_bucket: The S3 bucket to automatically sync outputs to.

    """
    if datastore is None:
        datastore = Datastore(path_stub=path_stub)

    io_kwargs = {
        "datastore": datastore,
        # "sync_to_s3_bucket": sync_to_s3_bucket,
        # "s3_default_access": s3_default_access,
    }

    # if s3 is not None:
    #     io_kwargs["s3"] = s3

    # if sync_to_s3_bucket:
    #     if s3 is None:
    #         io_kwargs["s3"] = default_io_s3_resource()

    io_managers: dict[str, dg.ConfigurableResource] = {
        "datastore": datastore,
        CSV_KEY: PandasCsvIoManager(**io_kwargs),
        JSON_KEY: JsonIOManager(**io_kwargs),
        NETCDF_KEY: XarrayNcIoManager(**io_kwargs),
        PARQUET_KEY: PandasParquetIoManager(**io_kwargs),
    }

    return datastore, io_managers


def latest_path_from_input_name(
    input_name: str,
    context: dg.OpExecutionContext,
) -> Path:
    """Get the latest materialized path for a given input asset.

    Parameters
    ----------
    - input_name (str): Name of input asset to get path for.
    - context (OpExecutionContext): The operation execution context.

    Returns
    -------
    - Path: The path metadata from the latest materialization event
    for the input asset.

    """
    try:
        from dagster._check.functions import CheckError
    except ModuleNotFoundError:
        from dagster_shared.check.functions import CheckError

    input_asset_key = context.asset_key_for_input(input_name)
    try:
        partition_keys = context.asset_partition_keys_for_input(input_name)
        latest_observation_record = context.instance.get_event_records(
            dg.EventRecordsFilter(
                event_type=dg.DagsterEventType.ASSET_MATERIALIZATION,
                asset_key=input_asset_key,
                asset_partitions=partition_keys,
            ),
            ascending=False,
            limit=1,
        )[0]
    except CheckError:
        latest_observation_record = context.instance.get_event_records(
            dg.EventRecordsFilter(
                event_type=dg.DagsterEventType.ASSET_MATERIALIZATION,
                asset_key=input_asset_key,
            ),
            ascending=False,
            limit=1,
        )[0]
    metadata = (
        latest_observation_record.event_log_entry.dagster_event.event_specific_data.materialization.metadata  # noqa: E501
    )
    path_meta = metadata["path"]

    return Path(path_meta.text)
