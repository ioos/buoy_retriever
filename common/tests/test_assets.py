"""Tests for shared automation conditions."""

import dagster as dg
import pytest

from common import assets as common_assets

DAILY = dg.DailyPartitionsDefinition(start_date="2025-01-01", end_date="2025-04-01")
MONTHLY = dg.MonthlyPartitionsDefinition(start_date="2025-01-01", end_date="2025-04-01")
EMPTY_MONTHS = {"2025-01-01", "2025-03-01"}


def build_defs(condition: dg.AutomationCondition) -> dg.Definitions:
    @dg.observable_source_asset(name="config_src")
    def config_src():
        return dg.DataVersion("v1")

    @dg.asset(partitions_def=DAILY)
    def daily():
        return None

    @dg.asset(
        partitions_def=MONTHLY,
        deps=[
            config_src,
            dg.AssetDep(
                daily,
                partition_mapping=dg.TimeWindowPartitionMapping(
                    allow_nonexistent_upstream_partitions=True,
                ),
            ),
        ],
        automation_condition=condition,
    )
    def monthly():
        return None

    return dg.Definitions(assets=[config_src, daily, monthly])


def new_condition() -> dg.AutomationCondition:
    return common_assets.auto_condition_eager_with_upstream_data(
        dg.AssetSelection.assets("daily"),
    )


def requested_months(result) -> set[str]:
    return set(result.get_requested_partitions(dg.AssetKey("monthly")))


def run_eval(defs, instance, cursor):
    return dg.evaluate_automation_conditions(
        defs=defs,
        instance=instance,
        cursor=cursor,
    )


def observe_config(instance, version: str) -> None:
    instance.report_runless_asset_event(
        dg.AssetObservation(
            asset_key="config_src",
            tags={"dagster/data_version": version},
        ),
    )


def materialize_daily(instance, partition: str) -> None:
    instance.report_runless_asset_event(
        dg.AssetMaterialization(asset_key="daily", partition=partition),
    )


@pytest.fixture
def defs():
    return build_defs(new_condition())


def test_empty_months_not_requested_on_first_evaluation(defs):
    instance = dg.DagsterInstance.ephemeral()
    materialize_daily(instance, "2025-02-10")
    result = run_eval(defs, instance, None)
    assert requested_months(result) <= {"2025-02-01"}
    assert not requested_months(result) & EMPTY_MONTHS


def test_config_observation_only_requests_months_with_daily_data(defs):
    instance = dg.DagsterInstance.ephemeral()
    materialize_daily(instance, "2025-02-10")
    result = run_eval(defs, instance, None)
    # Pretend the Feb month ran so only the config change remains.
    instance.report_runless_asset_event(
        dg.AssetMaterialization(asset_key="monthly", partition="2025-02-01"),
    )
    result = run_eval(defs, instance, result.cursor)
    assert requested_months(result) == set()

    observe_config(instance, "v2")
    result = run_eval(defs, instance, result.cursor)
    assert requested_months(result) == {"2025-02-01"}


def test_daily_materialization_requests_containing_month(defs):
    instance = dg.DagsterInstance.ephemeral()
    result = run_eval(defs, instance, None)
    assert requested_months(result) == set()

    materialize_daily(instance, "2025-03-05")
    result = run_eval(defs, instance, result.cursor)
    assert requested_months(result) == {"2025-03-01"}
