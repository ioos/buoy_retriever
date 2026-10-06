import dagster as dg
import numpy as np
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
        time_delta = float((monthly_ds.time[1] - monthly_ds.time[0]).dt.total_seconds())
        context.log.info(f"std: {std} time_delta {time_delta}")
        config.update(qartod_config.to_qartod_config(std=std, deltat=time_delta))

    context.log.info(f"qartod_config json: {config}")

    q_config = Config(config)

    qc_ds = monthly_ds.coords.to_dataset()

    is_profile = "depth" in monthly_ds.dims

    if is_profile:
        depths = monthly_ds.depth.values.tolist()
    else:
        depths = None
        sel = {}

    for call in q_config.calls:
        for depth_index, depth in enumerate(depths or [None]):
            """ Loop over the depths in the profile  or for a timeseries execute once
                Process each depth separately so that spike and flat line tests are not
                comparing  neighboring depth bins"""

            if is_profile:
                sel = {"depth": depth}

            subset_ds = monthly_ds.sel(
                **sel,
            )  # subset to one depth layer if profile, otherwise no subsetting

            kwargs = {
                "inp": subset_ds[call.stream_id].values,
                "tinp": subset_ds["time"].values,
                "zinp": depth,
            }

            results = call.run(**kwargs)
            for r in results:
                var_name = f"{call.stream_id}_{r.test}"

                if is_profile:
                    if var_name not in qc_ds:
                        empty = np.zeros(monthly_ds[call.stream_id].shape)
                        qc_ds[var_name] = (monthly_ds[call.stream_id].dims, empty)
                    qc_ds[var_name][:, depth_index] = r.results

                else:
                    qc_ds[var_name] = (monthly_ds[call.stream_id].dims, r.results)

    return qc_ds
