import dagster as dg
import sentry_sdk

from common import config, io
from common.backend_api import BackendAPIClient
from hohonu import HohonuConfig, HohonuDataset, defs_for_dataset, pipeline_slug

from hohonu_api import HohonuApi


@dg.definitions
def build_defs() -> dg.Definitions:
    """Build Dagster definitions and register pipeline with backend API"""
    with sentry_sdk.start_transaction(
        op="build_defs",
        name="Build Hohonu Pipeline Definitions",
    ):
        pipeline = config.PipelineConfig(
            slug=pipeline_slug,
            name="Hohonu",
            description="Fetch tide data from Hohonu's API",
            dataset_config=HohonuConfig,
        )

        api_client = BackendAPIClient()
        api_client.register_pipeline(pipeline)

        datastore, io_managers = io.common_resources(
            path_stub="hohonu",
        )

        defs = dg.Definitions(
            resources={
                "hohonu_api": HohonuApi(api_key=dg.EnvVar("HOHONU_API_KEY")),
                "datastore": datastore,
                **io_managers,
            },
        )

        datasets = api_client.datasets_for_pipeline(pipeline.slug, HohonuDataset)

        for dataset in datasets:
            dataset_defs = defs_for_dataset(dataset)
            defs = dg.Definitions.merge(defs, dataset_defs)

        return defs
