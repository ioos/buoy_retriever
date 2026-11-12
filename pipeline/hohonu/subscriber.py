"""
HTTP based subscriber for Hohonu datasets.
"""

from datetime import UTC
from datetime import datetime as dt

from common.config.dataset import ConfigState
from common.config.subscriber import Subscriber
from hohonu import PIPELINE_SLUG, HohonuDataset


class HohonuSubscriber(Subscriber[HohonuDataset]):
    dataset_type: type[HohonuDataset] = HohonuDataset
    pipeline_slug: str = PIPELINE_SLUG

    def new_config(self, dataset: HohonuDataset):
        """Backfills the most recent monthly partitions data when testing"""
        print(f"New configuration for dataset: {dataset.slug}")
        super().new_config(dataset)

        if dataset.config_state is ConfigState.TESTING:
            print(
                f"Dataset {dataset.slug} is testing, loading this months worth of data",
            )
            daily = dataset.daily_partitions()
            monthly = dataset.monthly_partitions()
            last_monthly_partition = monthly.get_last_partition_key()
            last_window = monthly.time_window_for_partition_key(last_monthly_partition)
            daily_partitions_for_last_month = daily.get_partition_keys_in_time_window(
                last_window,
            )
            today = dt.now(UTC)
            filtered_partitions = [
                p
                for p in daily_partitions_for_last_month
                if p <= today.strftime("%Y-%m-%d")
            ]

            self.dagster_client().materialize_assets_for_partitions(
                [dataset.daily_df_asset_key()],
                filtered_partitions,
            )

        if dataset.config_state is ConfigState.PUBLISHED:
            print(
                f"Dataset {dataset.slug} is in published state, probably should backfill everything since it's new",
            )

    def updated_config(self, new: HohonuDataset, old: HohonuDataset):
        print(f"Updated configuration for dataset: {new.slug}")
        if new.config.start_date != old.config.start_date:
            print(
                f"Dataset {new.slug} start date changed from {old.config.start_date} to {new.config.start_date}",
            )
            self.reload()
        super().updated_config(new, old)


if __name__ == "__main__":
    HohonuSubscriber().subscribe_loop()
