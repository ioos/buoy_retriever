from datetime import date
from typing import Annotated

import dagster as dg
import pandas as pd
import requests
import sentry_sdk
import xarray as xr
from pydantic import Field

from common import assets, config, io
from common.backend_api import BackendAPIClient
from common.pipeline.shared_pipeline import BaseTimeseriesConfig, monthly_pipeline_ds
from common.resource.aveva_resource import AvevaCredentials, AvevaResource
from common.sentry import SentryConfig

sentry = SentryConfig(pipeline_name="aveva")


class AvevaTimeseriesConfig(BaseTimeseriesConfig):
    """Configuration for S3 Timeseries Dataset."""

    namespace: Annotated[str, Field(description="Aveva namespace for the dataset")]

    tenant_id: Annotated[str, Field(description="Aveva tentan ID for the dataset")]


class AvevaTimeseriesDataset(config.DatasetBase):
    """S3 Timeseries Dataset."""

    config: Annotated[
        AvevaTimeseriesConfig,
        Field(description="The configuration for the dataset."),
    ]

    def daily_partition_path(self):
        """Path to daily partitions."""
        return (
            self.safe_slug
            + "/daily/{partition_key_dt:%Y}/{partition_key_dt:%m}/{partition_key_dt:%Y-%m-%d}.csv"
        )

    def monthly_partition_path(self):
        """Path to monthly partitions."""
        return (
            self.safe_slug
            # + "/monthly/{partition_key_dt:%Y}/"
            + "/"
            + self.slug
            + "_{partition_key_dt:%Y-%m}.nc"
        )


@dg.definitions
def build_defs() -> dg.Definitions:
    """Build Dagster definitions and register pipeline with backend API"""
    with sentry_sdk.start_transaction(
        op="build_defs",
        name="Build Aveva Pipeline Definitions",
    ):
        pipeline = config.PipelineConfig(
            slug="aveva_timeseries",
            name="Aveva timeseries",
            description="Fetch tide data from Hohonu's API",
            dataset_config=AvevaTimeseriesConfig,
        )

        api_client = BackendAPIClient()
        api_client.register_pipeline(pipeline)

        datastore, io_managers = io.common_resources(
            path_stub="aveva_timeseries",
        )

        aveva_credentials = AvevaCredentials(
            client_id=dg.EnvVar("AVEVA_CLIENT_ID"),
            client_secret=dg.EnvVar("AVEVA_CLIENT_SECRET"),
        )

        defs = dg.Definitions(
            resources={
                "aveva_resource": AvevaResource(
                    credentials=aveva_credentials,
                    ocs_resource="https://uswe.datahub.connect.aveva.com",
                ),
                "datastore": datastore,
                **io_managers,
            },
        )

        datasets = api_client.datasets_for_pipeline(
            pipeline.slug,
            AvevaTimeseriesDataset,
        )
        for dataset in datasets:
            dataset_defs = defs_for_dataset(dataset)
            defs = dg.Definitions.merge(defs, dataset_defs)

        return defs


def defs_for_dataset(dataset: AvevaTimeseriesDataset) -> dg.Definitions:  # noqa: C901
    """Definitions for a single Aveva Timeseries dataset."""
    common_asset_kwargs = {
        "key_prefix": ["aveva", dataset.safe_slug],
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
        metadata={io.DESIRED_PATH: dataset.daily_partition_path()},
        **io.CSV_ASSET_KWARGS,
        **common_asset_kwargs,
    )
    @sentry.capture_op_exceptions
    def daily_df(
        context: dg.AssetExecutionContext,
        aveva_resource: AvevaResource,
    ) -> pd.DataFrame:
        """Download daily dataframe from S3."""
        partition_date_string = context.asset_partition_key_for_output()
        partition_date = date.fromisoformat(partition_date_string)
        context.log.info(f"Partition date {partition_date_string}")
        context.log.info(f"date {partition_date}")
        start_window = f"{partition_date:%Y-%m-%d}T00:00:00Z"
        end_window = f"{partition_date:%Y-%m-%d}T23:59:59Z"
        # Step 4: test token by calling the base tenant endpoint
        msg_headers = {"Authorization": f"Bearer {aveva_resource.aveva_token}"}

        base_url = f"{aveva_resource.ocs_resource}/api/v1/Tenants/{dataset.config.tenant_id}/Namespaces/{dataset.config.namespace}"

        # start_date =

        streams = requests.get(
            f"{base_url}/Streams",
            headers=msg_headers,
            timeout=aveva_resource.aveva_timeout,
        ).json()

        combined_df = pd.DataFrame(columns=["time"])
        for stream in streams:
            context.log.info(f"Stream: {stream}")

            stream_data = requests.get(
                f"{base_url}/Streams/{stream['Id']}/Data",
                headers=msg_headers,
                timeout=aveva_resource.aveva_timeout,
                params={"startIndex": start_window, "endIndex": end_window},
            )

            if stream_data.status_code == 200:
                df = pd.DataFrame.from_dict(stream_data.json(), orient="columns")
                if df.empty:
                    continue
                print(f"DF COLUMNS {df.columns.tolist()}")
                df.loc[df["IsQuestionable"].isna(), "IsQuestionable"] = False
                df["IsQuestionable"] = df["IsQuestionable"].astype(bool)

                df["Timestamp"] = pd.to_datetime(df["Timestamp"]).dt.floor("s")
                df = df.rename(
                    columns={
                        "Value": stream["Name"],
                        "Timestamp": "time",
                        "IsQuestionable": f"{stream['Name']}_IsQuestionable",
                    },
                )
                combined_df = combined_df.merge(df, on="time", how="outer")

        return combined_df

    @dg.asset(
        ins={
            "daily_df": dg.AssetIn(
                partition_mapping=dg.TimeWindowPartitionMapping(
                    allow_nonexistent_upstream_partitions=True,
                ),
                metadata={io.ALLOW_MISSING_PARTITIONS: True},
            ),
        },
        partitions_def=monthly_partitions,
        metadata={
            io.DESIRED_PATH: dataset.monthly_partition_path(),
            # io.S3_DESIRED_PATH: config.s3_path(),
            # io.S3_PUBLIC: True,
        },
        automation_condition=assets.auto_condition_eager_allow_missing(),
        **io.NETCDF_ASSET_KWARGS,
        **common_asset_kwargs,
    )
    @sentry.capture_op_exceptions
    def monthly_ds(
        context: dg.AssetExecutionContext,
        daily_df: dict[str, pd.DataFrame],
    ) -> xr.Dataset:
        """Combine daily dataframes into a monthly NetCDF and apply transformations."""

        daily_dfs = []

        for df in daily_df.values():
            daily_dfs.append(df)
        return monthly_pipeline_ds(context, daily_dfs, dataset)

    dataset_assets = [daily_df, monthly_ds]

    return dg.Definitions(
        assets=dataset_assets,
    )
