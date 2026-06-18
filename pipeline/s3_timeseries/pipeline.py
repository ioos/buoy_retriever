from datetime import date, datetime
from textwrap import dedent
from typing import Annotated

import boto3
import dagster as dg
import pandas as pd
import sentry_sdk
import xarray as xr
from dagster_aws.s3.sensor import get_objects
from parse import parse
from pydantic import BaseModel, Field

from common import assets, config, io
from common.backend_api import BackendAPIClient
from common.config import s3_source
from common.pipeline.shared_pipeline import BaseTimeseriesConfig, monthly_pipeline_ds
from common.readers.pandas_csv import PandasCSVReader
from common.resource.s3fs_resource import S3Credentials, S3FSResource
from common.sentry import SentryConfig

sentry = SentryConfig(pipeline_name="s3_timeseries")


class DayGlob(BaseModel):
    """Configure glob patterns for daily files in S3."""

    day_pattern: Annotated[
        str | None,
        Field(
            description=dedent("""
                Glob pattern for daily files.
                The `partition_date` is available for formatting
                """),
            examples=[
                "EW01_ADCP_{partition_date:%Y%m%d}_*.txt",
                "EW01_wave_ioos_{partition_date:%Y%m%d}_*.txt",
            ],
        ),
    ] = None


class S3TimeseriesConfig(
    BaseTimeseriesConfig,
    s3_source.S3SourceMixin,
):
    """Configuration for S3 Timeseries Dataset."""

    reader: PandasCSVReader

    source_time_var: str = "datetime"

    file_pattern: Annotated[DayGlob, Field(description="Source file name pattern")]


class S3TimeseriesDataset(config.DatasetBase):
    """S3 Timeseries Dataset."""

    config: Annotated[
        S3TimeseriesConfig,
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


def defs_for_dataset(dataset: S3TimeseriesDataset) -> dg.Definitions:  # noqa: C901
    """Definitions for a single S3 Timeseries dataset."""
    common_asset_kwargs = {
        "key_prefix": ["s3_timeseries", dataset.safe_slug],
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
    def daily_df(context: dg.AssetExecutionContext, s3fs: S3FSResource) -> pd.DataFrame:
        """Download daily dataframe from S3."""
        partition_date_string = context.asset_partition_key_for_output()
        partition_date = date.fromisoformat(partition_date_string)

        day_glob = (
            dataset.config.s3_source.bucket
            + dataset.config.s3_source.prefix
            + dataset.config.file_pattern.day_pattern.format(
                partition_date=partition_date,
            )
        )

        context.log.info(
            f"Reading daily data for {partition_date_string} from S3 with glob: {day_glob}",
        )

        s3_keys = s3fs.fs.glob(day_glob)
        s3_keys.sort()

        context.log.info(f"Found {len(s3_keys)} files: \n{s3_keys}")
        context.add_output_metadata({"Source S3 keys": dg.MetadataValue.json(s3_keys)})

        daily_dfs = []

        for day_f in s3_keys:
            context.log.debug(f"Reading {day_f}")
            with s3fs.fs.open(day_f, "rb") as f:
                df = dataset.config.reader.read_df(f)

                if dataset.config.variable_converter is not None:
                    for converter in dataset.config.variable_converter:
                        df = converter.convert(df)

                daily_dfs.append(df)

        df = pd.concat(daily_dfs)

        df[dataset.config.source_time_var] = pd.to_datetime(
            df[dataset.config.source_time_var],
        )
        if dataset.config.dataset_type == "profile":
            indx_var = [dataset.config.source_time_var, "depth"]
        else:
            indx_var = dataset.config.source_time_var
        df = df.sort_values(indx_var)
        df = df.reset_index(drop=True)

        return df

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

        return monthly_pipeline_ds(context, daily_df, dataset, "NAN")

    daily_job = dg.define_asset_job(
        f"update_{dataset.safe_slug}_daily",
        selection=[daily_df],
    )

    @dg.sensor(
        job=daily_job,
        name=dataset.safe_slug + "_s3_sensor",
        minimum_interval_seconds=5 * 60,
    )
    def s3_sensor(context: dg.SensorEvaluationContext, s3_credentials: S3Credentials):
        """Sensor to detect new files for a day in S3."""
        with sentry_sdk.start_transaction(
            op=f"{dataset.safe_slug}_s3_sensor",
            name=f"S3 Sensor for {dataset.safe_slug}",
        ):
            since_time = context.cursor or None
            if since_time:
                since_time = datetime.fromisoformat(since_time)

            client = boto3.client(
                "s3",
                aws_access_key_id=s3_credentials.access_key_id,
                aws_secret_access_key=s3_credentials.secret_access_key,
            )
            file_start = dataset.config.file_pattern.day_pattern.split("{")[0]

            new_s3_keys = get_objects(
                bucket=dataset.config.s3_source.bucket,
                prefix=file_start,
                since_last_modified=since_time,
                client=client,
            )
            if not new_s3_keys:
                return dg.SkipReason("No new files found in S3.")

            existing_partitions = set()
            known_partitions = set(daily_partitions.get_partition_keys())
            for run in context.instance.get_runs(
                filters=dg.RunsFilter(
                    job_name=daily_job.name,
                    statuses=[
                        dg.DagsterRunStatus.QUEUED,
                        dg.DagsterRunStatus.STARTING,
                        dg.DagsterRunStatus.STARTED,
                        dg.DagsterRunStatus.NOT_STARTED,
                    ],
                ),
            ):
                try:
                    existing_partitions.add(run.tags["dagster/partition"])
                except KeyError:
                    pass

            for key in new_s3_keys:
                object_key = key.get("Key")

                object_name = object_key.removeprefix(dataset.config.s3_source.prefix)
                name_pattern = dataset.config.file_pattern.day_pattern.replace(
                    "*",
                    "{}",
                )
                result = parse(name_pattern, object_name)
                dt = result.named["partition_date"].strftime("%Y-%m-%d")

                if dt not in existing_partitions:
                    last_modified = key.get("LastModified")

                    if since_time is None or last_modified > since_time:
                        existing_partitions.add(dt)
                        run_key = f"{dt}_{last_modified.isoformat()}"

                        if dt in known_partitions:
                            yield dg.RunRequest(
                                run_key=run_key,
                                partition_key=dt,
                            )
                        else:
                            context.log.info(
                                f"Skipping partition {dt} as it is not a known partition",
                            )

            latest_key_dt = max(key.get("LastModified") for key in new_s3_keys)
            context.update_cursor(latest_key_dt.isoformat())

    dataset_assets = [daily_df, monthly_ds]

    return dg.Definitions(
        assets=dataset_assets,
        sensors=[
            s3_sensor,
            dg.AutomationConditionSensorDefinition(
                dataset.safe_slug + "_automation_sensor",
                target=dataset_assets,
            ),
        ],
    )


@dg.definitions
def build_defs() -> dg.Definitions:
    """Build definitions for S3 Timeseries pipeline and register with backend."""
    with sentry_sdk.start_transaction(
        op="build_defs",
        name="Build S3 Timeseries Pipeline Definitions",
    ):
        pipeline = config.PipelineConfig(
            slug="s3_timeseries",
            name="S3 Timeseries",
            description="Fetch time series data from CSV files in S3",
            dataset_config=S3TimeseriesConfig,
        )

        api_client = BackendAPIClient()
        api_client.register_pipeline(pipeline)

        datastore, io_managers = io.common_resources(path_stub="s3_timeseries")

        credentials = S3Credentials(
            access_key_id=dg.EnvVar("S3_TS_ACCESS_KEY_ID"),
            secret_access_key=dg.EnvVar("S3_TS_SECRET_ACCESS_KEY"),
        )

        defs = dg.Definitions(
            resources={
                "s3_credentials": credentials,
                "s3fs": S3FSResource(
                    credentials=credentials,
                    region_name="us-east-1",
                ),
                "datastore": datastore,
                **io_managers,
            },
        )

        datasets = api_client.datasets_for_pipeline(pipeline.slug, S3TimeseriesDataset)
        for dataset in datasets:
            dataset_defs = defs_for_dataset(dataset)
            defs = dg.Definitions.merge(defs, dataset_defs)

        return defs
