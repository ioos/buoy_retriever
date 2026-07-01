from pathlib import Path

import dagster as dg
import pandas as pd

from common.io import tags as io
from common.io.datastore import Datastore
from common.io.parquet_io import PandasParquetIoManager


def test_parquet_io_handle_unpartitioned_output(tmp_path: Path):
    """Test we can write and read a parquet file with the parquet IO Manager"""
    datastore = Datastore(path_stub="test_stub", test_path=str(tmp_path))
    parquet_io = PandasParquetIoManager(datastore=datastore)

    output_context = dg.build_output_context(
        definition_metadata={io.DESIRED_PATH: "test_output.parquet"},
    )

    # Create a sample DataFrame
    data = {
        "a": [1, 2, 3],
        "b": [4, 5, 6],
    }

    df_to_write = pd.DataFrame(data)

    # Handle output (write the DataFrame to parquet)
    parquet_io.handle_output(output_context, df_to_write)

    # Handle input (read the DataFrame from parquet)
    df_read = pd.read_parquet(tmp_path / "test_stub" / "test_output.parquet")

    # Verify that the written and read DataFrames are the same
    pd.testing.assert_frame_equal(df_to_write, df_read)


def test_parquet_io_handle_partitioned_output(tmp_path: Path):
    """Test we can write and read a partitioned parquet file with the parquet IO Manager"""
    datastore = Datastore(path_stub="test_stub", test_path=str(tmp_path))
    parquet_io = PandasParquetIoManager(datastore=datastore)

    partition_key = "2023-10-01"
    output_context = dg.build_output_context(
        definition_metadata={
            io.DESIRED_PATH: "partitions/{partition_key_dt:%Y-%m-%d}.parquet",
        },
        partition_key=partition_key,
    )

    # Create a sample DataFrame
    data = {
        "x": [10, 20, 30],
        "y": [40, 50, 60],
    }

    df_to_write = pd.DataFrame(data)

    # Handle output (write the DataFrame to parquet)
    parquet_io.handle_output(output_context, df_to_write)

    # Handle input (read the DataFrame from parquet)
    df_read = pd.read_parquet(
        tmp_path / "test_stub" / "partitions" / f"{partition_key}.parquet",
    )

    # Verify that the written and read DataFrames are the same
    pd.testing.assert_frame_equal(df_to_write, df_read)


def test_parquet_io_load_unpartitioned_input(tmp_path: Path):
    """Test we can read a parquet file with the parquet IO Manager"""
    datastore = Datastore(path_stub="test_stub", test_path=str(tmp_path))
    parquet_io = PandasParquetIoManager(datastore=datastore)

    # Create a sample DataFrame and write it to parquet
    data = {
        "m": [7, 8, 9],
        "n": [10, 11, 12],
    }

    df_to_write = pd.DataFrame(data)
    test_dir = tmp_path / "test_stub"
    test_dir.mkdir(parents=True, exist_ok=True)
    df_to_write.to_parquet(test_dir / "input_data.parquet", index=False)

    # Now build an input context to read the parquet
    input_context = dg.build_input_context(
        upstream_output=dg.build_output_context(
            definition_metadata={io.DESIRED_PATH: "input_data.parquet"},
        ),
    )

    # Load the DataFrame from parquet
    df_read = parquet_io.load_input(input_context)

    # Verify that the written and read DataFrames are the same
    pd.testing.assert_frame_equal(df_to_write, df_read)
