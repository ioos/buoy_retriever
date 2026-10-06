import dagster as dg
import xarray as xr
from ioos_qc.config import Config

from common.config.qartod_config import QartodConfig


def qartod_pipeline_ds(
    context: dg.AssetExecutionContext,
    monthly_ds: xr.Dataset,
    qartod_configs: [QartodConfig],
) -> xr.Dataset:
    """Run qartod on the aggregated monthly results"""

    context.log.info(monthly_ds)

    """Generate the qartod config for this dataset
       Set standard deviation for config entries that are based on std
    """
    config = {}
    for qartod_config in qartod_configs:
        context.log.info(
            f"qartod_config: {qartod_config.variable_name} : {qartod_config.qartod_test_config}",
        )
        std = monthly_ds[qartod_config.variable_name].std().data

        config.update(qartod_config.to_qartod_config(std))

    context.log.info(f"qartod_config json: {config}")

    q_config = Config(config)

    qc_ds = monthly_ds.coords.to_dataset()

    if "depth" in monthly_ds.dims:
        depths = monthly_ds.depth.values
    else:
        depths = None

    for call in q_config.calls:
        kwargs = {
            "inp": monthly_ds[call.stream_id].values,
            "tinp": monthly_ds.time.values,
            "zinp": depths,
        }

        results = call.run(**kwargs)
        for r in results:
            var_name = f"{call.stream_id}_{r.test}"

            qc_ds[var_name] = (monthly_ds[call.stream_id].dims, r.results)

    return qc_ds
