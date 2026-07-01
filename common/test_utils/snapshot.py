import functools
import os
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import dagster as dg
import pytest
from pytest_regressions.common import perform_regression_check

from common.io import (
    Datastore,
    PandasCsvIoManager,
    PandasParquetIoManager,
    XarrayNcIoManager,
)
from common.io.base import IOManagerBase

if TYPE_CHECKING:
    import pandas as pd
    import xarray as xr
    from pytest_datadir.plugin import LazyDataDir


class IoManagerRegressionFixture[T](ABC):
    """Round-trip an object through its IOManager and regression-check the file."""

    io_manager_cls: type[IOManagerBase]
    extension: str

    def __init__(
        self,
        datadir: "LazyDataDir",
        original_datadir: Path,
        request: pytest.FixtureRequest,
    ) -> None:
        self.datadir = datadir
        self.original_datadir = original_datadir
        self.request = request
        self._force_regen = False
        self._with_test_class_names = False
        # IO managers need a datastore even though we don't exercise that path.
        self.io_manager = self.io_manager_cls(
            datastore=Datastore(path_stub="stub", test_path="placeholder"),
        )

    def _load(self, filename: Path) -> T:
        return self.io_manager.load_from_path(dg.build_input_context(), filename)

    def _dump(self, data_object: T, filename: Path) -> None:
        self.io_manager.dump_to_path(dg.build_output_context(), data_object, filename)

    @abstractmethod
    def _compare(self, obtained: T, expected: T, **kwargs) -> None:
        """Assert obtained == expected, raising AssertionError otherwise."""

    def _check_fn(self, obtained_file: Path, expected_file: Path, **kwargs) -> None:
        self._compare(self._load(obtained_file), self._load(expected_file), **kwargs)

    def check(
        self,
        data_object: T,
        basename: str | None = None,
        fullpath: os.PathLike[str] | None = None,
        **compare_kwargs,
    ) -> None:
        perform_regression_check(
            datadir=self.datadir,
            original_datadir=self.original_datadir,
            request=self.request,
            check_fn=functools.partial(self._check_fn, **compare_kwargs),
            dump_fn=functools.partial(self._dump, data_object),
            extension=self.extension,
            basename=basename,
            fullpath=fullpath,
            force_regen=self._force_regen,
            with_test_class_names=self._with_test_class_names,
        )


class PandasCsvIoRegressionFixture(IoManagerRegressionFixture["pd.DataFrame"]):
    extension = ".csv"
    io_manager_cls = PandasCsvIoManager

    def _compare(
        self,
        obtained: "pd.DataFrame",
        expected: "pd.DataFrame",
        **kwargs,
    ) -> None:
        import pandas as pd

        pd.testing.assert_frame_equal(obtained, expected, **kwargs)


class PandasParquetIoRegressionFixture(PandasCsvIoRegressionFixture):
    extension = ".parquet"
    io_manager_cls = PandasParquetIoManager


class NcIoRegressionFixture(IoManagerRegressionFixture["xr.Dataset"]):
    extension = ".nc"
    io_manager_cls = XarrayNcIoManager

    def _compare(
        self,
        obtained: "xr.Dataset",
        expected: "xr.Dataset",
        method: Literal["equal", "identical", "allclose"] = "equal",
        **kwargs,
    ) -> None:
        import xarray as xr

        asserts = {
            "equal": xr.testing.assert_equal,
            "identical": xr.testing.assert_identical,
            "allclose": xr.testing.assert_allclose,
        }
        if method not in asserts:
            raise ValueError(
                f"Unknown method {method!r}; choose from {sorted(asserts)}",
            )
        asserts[method](obtained, expected, **kwargs)


@pytest.fixture
def nc_io_regression(
    datadir: "LazyDataDir",
    original_datadir: Path,
    request: pytest.FixtureRequest,
) -> NcIoRegressionFixture:
    return NcIoRegressionFixture(datadir, original_datadir, request)


@pytest.fixture
def pandas_parquet_regression(
    datadir: "LazyDataDir",
    original_datadir: Path,
    request: pytest.FixtureRequest,
) -> PandasParquetIoRegressionFixture:
    return PandasParquetIoRegressionFixture(datadir, original_datadir, request)


@pytest.fixture
def pandas_csv_regression(
    datadir: "LazyDataDir",
    original_datadir: Path,
    request: pytest.FixtureRequest,
) -> PandasCsvIoRegressionFixture:
    return PandasCsvIoRegressionFixture(datadir, original_datadir, request)
