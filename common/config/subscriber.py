import time
from typing import TypeVar

from pydantic import BaseModel, Field

from .dataset import DatasetBase
from common.dagster_api import DagsterAPIClient
from common.backend_api import BackendAPIClient



DatasetType = TypeVar("DatasetType", bound=DatasetBase)


class Subscriber[DatasetType](BaseModel):
    dataset_type: type[DatasetType] = Field(..., description="The dataset type this subscriber is associated with")
    pipeline_slug: str = Field(..., description="The slug of the pipeline this subscriber is associated with")

    _dagster_api_client: DagsterAPIClient | None = None
    _reloaded: bool = False

    def subscribe_loop(self, sleep_seconds: int = 60):
        """Subscribe to dataset updates in a loop.
        
        This method continuously checks for updates to dataset configuration, and calls 
        `new_config` for new datasets and `updated_config` for updated datasets, which can be overridden as needed.
        """
        datasets = {}
        backend_client = BackendAPIClient()

        initial_load = True

        while True:
            # Fetch the latest dataset configurations from the backend
            new_datasets = backend_client.datasets_for_pipeline(self.pipeline_slug, self.dataset_type)
            self._reloaded = False

            for ds in new_datasets:
                slug = ds.slug
                edited = ds.edited

                if initial_load:
                    self.initial_config(ds)
                elif slug not in datasets:
                    self.new_config(ds)
                elif edited != datasets[slug].edited:
                    self.updated_config(ds, datasets[slug])

                datasets[slug] = ds

            initial_load = False

            print("Checked datasets at", time.strftime("%Y-%m-%d %H:%M:%S"))
            time.sleep(sleep_seconds)

    def reload(self):
        """Trigger a reload of the repository if it hasn't already happened this iteration."""
        if self._reloaded:
            return
        self._reloaded = True
        self.dagster_client().reload_repo()

    def report_config_observation(self, dataset: DatasetType):
        """Report an observation of a datasets configuration to Dagster"""
        self.dagster_client().report_observation(
            dataset.config_asset_key().parts,
            dataset.edited.isoformat(),
            {"last_modified": dataset.edited.isoformat(), "config": dataset.model_dump_json()}
        )

    def initial_config(self, dataset: DatasetType):
        """Handle the event when a dataset is initially loaded."""
        self.report_config_observation(dataset)

    def new_config(self, dataset: DatasetType):
        """Handle the event when a dataset is newly added to a running instance.

        Generally requires a reload as the repository needs to be aware of the new dataset.
        This can also be used to trigger a backfill of data based on the config state.
        """
        self.reload()
        self.report_config_observation(dataset)

    def updated_config(self, new: DatasetType, old: DatasetType):
        """Handle the event when a dataset is updated.
        
        Override and call `self.reload()` if the update requires reloading the full repository, 
        such as a change to partitions.
        """
        self.report_config_observation(new)

    def dagster_client(self) -> DagsterAPIClient:
            """Get the Dagster API client for this subscriber."""
            if self._dagster_api_client is None:
                self._dagster_api_client = DagsterAPIClient(repository=self.pipeline_slug)
            return self._dagster_api_client
