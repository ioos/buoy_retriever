import dagster as dg


def auto_condition_eager_allow_missing():
    """Allow missing upstream partitions but still eagerly execute"""
    return (
        dg.AutomationCondition.eager()
        .without(~dg.AutomationCondition.any_deps_missing())
        .without(dg.AutomationCondition.in_latest_time_window())
        .with_label("eager_allow_missing")
    )


def auto_condition_eager_with_upstream_data(data_deps: dg.AssetSelection):
    """eager_allow_missing, but only for partitions where at least one
    upstream partition in `data_deps` has been materialized."""
    has_upstream_data = (
        dg.AutomationCondition.any_deps_match(~dg.AutomationCondition.missing())
        .allow(data_deps)
        .with_label("has_upstream_data")
    )
    return (auto_condition_eager_allow_missing() & has_upstream_data).with_label(
        "eager_with_upstream_data",
    )
