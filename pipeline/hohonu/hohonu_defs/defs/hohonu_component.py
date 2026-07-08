"""State-backed component for the Hohonu pipeline.

Dataset configs are fetched from the backend REST API. Because the set of
datasets (and therefore the asset graph) cannot be known without calling the
API, this is a :class:`dagster.StateBackedComponent`: the API call happens in
``write_state_to_path`` (only on ``dg utils refresh-defs-state`` or dev
refresh) and the cached JSON is turned into definitions in
``build_defs_from_state`` on every code-server load.
"""

import json
from pathlib import Path

import dagster as dg
import sentry_sdk
from dagster.components import (
    DefsStateConfig,
    DefsStateConfigArgs,
    ResolvedDefsStateConfig,
)
from pydantic import ValidationError

from common import config, io
from common.backend_api import BackendAPIClient
from common.sentry import SentryConfig
from hohonu import HohonuConfig, HohonuDataset, defs_for_dataset

from hohonu_api import HohonuApi

sentry = SentryConfig(pipeline_name="hohonu")

PIPELINE = config.PipelineConfig(
    slug="hohonu",
    name="Hohonu",
    description="Fetch tide data from Hohonu's API",
    dataset_config=HohonuConfig,
)


class HohonuStateComponent(dg.StateBackedComponent, dg.Model, dg.Resolvable):
    """Build Hohonu definitions from dataset configs cached from the backend API."""

    defs_state: ResolvedDefsStateConfig = DefsStateConfigArgs.local_filesystem()

    @property
    def defs_state_config(self) -> DefsStateConfig:
        return DefsStateConfig.from_args(
            self.defs_state,
            default_key=self.__class__.__name__,
        )

    def write_state_to_path(self, state_path: Path) -> None:
        """Register the pipeline and persist the raw dataset configs from the API."""
        with sentry_sdk.start_transaction(
            op="refresh_defs_state",
            name="Refresh Hohonu defs state",
        ):
            api_client = BackendAPIClient()
            api_client.register_pipeline(PIPELINE)
            raw_datasets = api_client.raw_datasets_for_pipeline(PIPELINE.slug)
            state_path.write_text(json.dumps(raw_datasets))

    def _base_defs(self) -> dg.Definitions:
        """Resources shared by every Hohonu dataset."""
        datastore, io_managers = io.common_resources(path_stub="hohonu")
        return dg.Definitions(
            resources={
                "hohonu_api": HohonuApi(api_key=dg.EnvVar("HOHONU_API_KEY")),
                "datastore": datastore,
                **io_managers,
            },
        )

    def build_defs_from_state(
        self,
        context: dg.ComponentLoadContext,
        state_path: Path | None,
    ) -> dg.Definitions:
        """Validate cached dataset configs and merge per-dataset definitions."""
        defs = self._base_defs()
        if state_path is None:
            return defs

        raw_datasets = json.loads(state_path.read_text())
        for raw_dataset in raw_datasets:
            try:
                dataset = HohonuDataset(**raw_dataset)
            except ValidationError as e:
                print(f"Error validating dataset {raw_dataset}: {e}")
                continue
            defs = dg.Definitions.merge(defs, defs_for_dataset(dataset))

        return defs


@dg.component_instance
def load(context: dg.ComponentLoadContext) -> HohonuStateComponent:
    """Instantiate the component in Python (no YAML) so config stays in code."""
    return HohonuStateComponent()
