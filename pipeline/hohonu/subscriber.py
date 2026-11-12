"""
HTTP based subscriber for Hohonu datasets.
"""

import time

from common.backend_api import BackendAPIClient
from common.config.dataset import DatasetBase, ConfigState
from common.dagster_api import DagsterAPIClient
from common.config.subscriber import Subscriber
from hohonu import PIPELINE_SLUG, HohonuDataset

dagster_client = DagsterAPIClient(repository=PIPELINE_SLUG)


def notify_new_or_updated(ds: HohonuDataset):
    key = ds.config_asset_key()
    print(f"Notifying new or updated dataset: {ds.slug}")

    dagster_client.report_observation(
        key.parts,
        ds.edited.isoformat(),
        {"last_modified": ds.edited.isoformat(), "config": ds.model_dump_json()},
    )


# def main():
#     """Check dataset configurations for updates and notify Dagster of any changes."""
#     dataset_configs = {}

#     client = BackendAPIClient()

#     while True:
#         datasets = client.datasets_for_pipeline(PIPELINE_SLUG, HohonuDataset)

#         reload = False

#         for ds in datasets:
#             slug = ds.slug
#             edited = ds.edited

#             if slug not in dataset_configs or dataset_configs[slug].edited != edited:
#                 notify_new_or_updated(ds)

#             old_dataset = dataset_configs.get(slug)

#             # changes that require a reload
#             if old_dataset and (old_dataset.config.start_date != ds.config.start_date):
#                 print(f"Dataset {slug} requires reload due to changed start date")
#                 reload = True
#                 # use differences in start dates to trigger explicit load of new days, or reload of all

#             dataset_configs[slug] = ds

#         if reload:
#             dagster_client.reload_repo()

#         print("Checked datasets at", time.strftime("%Y-%m-%d %H:%M:%S"))
#         time.sleep(60)

class HohonuSubscriber(Subscriber[HohonuDataset]):
    dataset_type: type[HohonuDataset] = HohonuDataset
    pipeline_slug: str = PIPELINE_SLUG

    def new_config(self, dataset: HohonuDataset):
        """Backfills the most recent monthly partitions data when testing"""
        print(f"New configuration for dataset: {dataset.slug}")
        super().new_config(dataset)

        if dataset.config_state is ConfigState.TESTING:
            print(f"Dataset {dataset.slug} is in testing state")
            daily = dataset.daily_partitions()
            monthly = dataset.monthly_partitions()
            last_monthly_partition = monthly.get_last_partition_key()
            last_window = monthly.time_window_for_partition_key(last_monthly_partition)
            print(f"Last monthly partition for dataset {dataset.slug}: {last_monthly_partition}")
            print(f"Time window for last monthly partition: {last_window}")

            daily_partitions_for_last_month = daily.get_partition_keys_in_time_window(last_window)
            print(f"Daily partitions for last monthly partition: {daily_partitions_for_last_month}")
            self.dagster_client().materialize_assets_for_partitions(
                dataset.daily_df_asset_key(),
                daily_partitions_for_last_month,
            )

        if dataset.config_state is ConfigState.PUBLISHED:
            print(f"Dataset {dataset.slug} is in published state, probably should backfill everything if it's new")
        
    

    def updated_config(self, new: HohonuDataset, old: HohonuDataset):
        print(f"Updated configuration for dataset: {new.slug}")
        # breakpoint()

        super().updated_config(new, old)


if __name__ == "__main__":
    HohonuSubscriber().subscribe_loop()
