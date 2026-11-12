from textwrap import dedent
from typing import Annotated

import dagster as dg
from pydantic import BaseModel, Field

from common import config
from common.config import s3_source
from common.pipeline.shared_pipeline import BaseTimeseriesConfig
from common.readers.pandas_csv import PandasCSVReader

PIPELINE_SLUG = "s3_timeseries"


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

    @property
    def key_prefix(self):
        return [PIPELINE_SLUG, self.safe_slug]

    def daily_partitions(self):
        """Generate daily partitions"""
        return dg.DailyPartitionsDefinition(
            start_date=self.config.start_date.isoformat(),
            end_offset=1,
        )

    def monthly_partitions(self):
        """Generate monthly partitions"""
        return dg.MonthlyPartitionsDefinition(
            start_date=self.config.start_date.strftime("%Y-%m-01"),
            end_offset=1,
        )

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
