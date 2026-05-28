"""Load and save parquet files with Pandas to the datastore"""

from pathlib import Path

import pandas as pd
from dagster import InputContext, MetadataValue, OutputContext

from .base import IOManagerBase


class PandasParquetIoManager(IOManagerBase):
    """Load and save parquet files with Pandas"""

    def dump_to_path(
        self,
        context: OutputContext,
        obj: pd.DataFrame,
        path: Path,
    ) -> None:
        """Save dataframe to a given path as a parquet file"""
        with path.open("wb") as f:
            obj.to_parquet(f, index=True)

        context.add_output_metadata(
            {
                "pandas_df.head": MetadataValue.md(f"{obj.head().to_markdown()}"),
                "pandas_df.tail": MetadataValue.md(f"{obj.tail().to_markdown()}"),
                "pandas_df.describe": MetadataValue.md(
                    f"{obj.describe().to_markdown()}",
                ),
            },
        )

    def load_from_path(self, context: InputContext, path: Path) -> pd.DataFrame:
        """Load a dataframe from a given parquet file path"""
        with path.open("rb") as f:
            return pd.read_parquet(f)
