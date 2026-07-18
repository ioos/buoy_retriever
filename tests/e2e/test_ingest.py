"""Full ingest: materialize real Dagster assets for the `boothbay_dmr`
dataset (seeded by the `boothbay_dmr_seeded` fixture) via the Dagster GraphQL API,
and verify the resulting NetCDF/parquet output lands on the shared-fs
volume. The Hohonu API call itself is replayed from the existing
`test_daily_asset.yaml` VCR cassette by `pipeline/hohonu/sitecustomize.py`
(see docker-compose.e2e.yaml) -- no real Hohonu credentials involved.

Runs are launched with the in-process executor (via `run_config`, not by
changing the job's own `executor_def`): Dagster's default multiprocess
executor launches each step in a `multiprocessing`-spawned subprocess using
`-S -E`, which skips `site` processing and drops PYTHONPATH -- exactly the
mechanism sitecustomize.py relies on -- so a real step subprocess would
silently bypass the cassette and hit the real Hohonu API. Forcing
in-process execution for this run only keeps everything in the one process
Dagster's run launcher already spawned normally (inheriting the container's
environment), without changing how the job executes in production.
"""

import xarray as xr
from conftest import Stack, wait_until
from dagster import DagsterRunStatus
from dagster_graphql import DagsterGraphQLClient

# Matches the partition covered by
# docker-data/test-data/hohonu/cassettes/test_hohonu_pipeline/test_daily_asset.yaml
PARTITION_KEY = "2025-09-30"

MONTHLY_PARTITION_KEY = "2025-09-01"

# daily_df is daily-partitioned and monthly_ds/monthly_parquet are
# monthly-partitioned, so Dagster can't fold them into one implicit asset
# job -- pipeline/hohonu/hohonu.py's defs_for_dataset() defines one explicit
# job per partition scheme instead (confirmed via the repositoryOrError {
# assetNodes { assetKey { path } } } GraphQL query against the running
# location, which also showed there's no separate "monthly_nc" asset --
# monthly_ds writes the NetCDF itself, via its IO manager).
DAILY_JOB = "boothbay_dmr_daily_job"
MONTHLY_JOB = "boothbay_dmr_monthly_job"


def _run_job_to_completion(
    dagster_client: DagsterGraphQLClient,
    *,
    job_name: str,
    partition_key: str,
) -> None:
    run_id = dagster_client.submit_job_execution(
        job_name=job_name,
        repository_location_name="hohonu",
        repository_name="__repository__",
        run_config={"execution": {"config": {"in_process": {}}}},
        tags={"dagster/partition": partition_key},
    )

    def _run_finished():
        status = dagster_client.get_run_status(run_id)
        return (
            status
            if status in (DagsterRunStatus.SUCCESS, DagsterRunStatus.FAILURE)
            else None
        )

    status = wait_until(
        _run_finished,
        timeout=180,
        interval=3,
        message=f"run {run_id} to finish",
    )
    assert status == DagsterRunStatus.SUCCESS, (
        f"{job_name} run {run_id} did not succeed: {status}. "
        f"Check `docker compose -p buoy_retriever_e2e logs hohonu dagster_daemon` for details."
    )


def test_materialize_boothbay_dmr(
    boothbay_dmr_seeded: None,
    dagster_client: DagsterGraphQLClient,
    e2e_stack: Stack,
) -> None:
    """Materialize one daily and one monthly partition end to end.

    Launches the daily job (fetch from the replayed Hohonu API cassette)
    then the monthly job (aggregate to NetCDF/parquet) via GraphQL, waits
    for both runs to succeed, and verifies the NetCDF that landed on the
    shared-fs volume from the host side: the renamed/unit-converted
    variable exists and carries its CF standard_name from attributes.yaml.
    """
    _run_job_to_completion(
        dagster_client,
        job_name=DAILY_JOB,
        partition_key=PARTITION_KEY,
    )
    _run_job_to_completion(
        dagster_client,
        job_name=MONTHLY_JOB,
        partition_key=MONTHLY_PARTITION_KEY,
    )

    # common/paths.py: DATASET_PATH / path_stub / <DESIRED_PATH>, path_stub="hohonu"
    # (see io.common_resources() in pipeline/hohonu/pipeline.py's build_defs()).
    monthly_nc_dir = e2e_stack.shared_fs_dir / "datasets" / "hohonu" / "boothbay_dmr"
    nc_files = sorted(monthly_nc_dir.rglob("*.nc"))
    assert nc_files, f"no NetCDF output found under {monthly_nc_dir}"

    with xr.open_dataset(nc_files[-1]) as ds:
        assert "navd88_meters" in ds.data_vars, ds.data_vars
        assert (
            ds["navd88_meters"].attrs["standard_name"]
            == "sea_surface_height_above_geopotential_datum"
        )
