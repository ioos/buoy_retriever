"""
HTTP based subscriber for Hohonu datasets.
"""

import time

from common.backend_api import BackendAPIClient
from common.dagster_api import DagsterAPICClient
from hohonu import HohonuDataset

dagster_client = DagsterAPICClient(repository="hohonu")


def notify_new_or_updated(ds: HohonuDataset):
    key = ds.config_asset_key()
    print(f"Notifying new or updated dataset: {ds.slug}")

    dagster_client.report_observation(
        key.parts,
        ds.edited.isoformat(),
        {"last_modified": ds.edited.isoformat(), "config": ds.model_dump_json()},
    )


def main():
    """Check dataset configurations for updates and notify Dagster of any changes."""
    dataset_configs = {}

    client = BackendAPIClient()

    while True:
        datasets = client.datasets_for_pipeline("hohonu", HohonuDataset)

        reload = False

        for ds in datasets:
            slug = ds.slug
            edited = ds.edited

            if slug not in dataset_configs or dataset_configs[slug].edited != edited:
                notify_new_or_updated(ds)

            old_dataset = dataset_configs.get(slug)

            # changes that require a reload
            if old_dataset and (old_dataset.config.start_date != ds.config.start_date):
                print(f"Dataset {slug} requires reload due to changed start date")
                reload = True
                # use differences in start dates to trigger explicit load of new days, or reload of all

            dataset_configs[slug] = ds

        if reload:
            dagster_client.reload_repo()

        print("Checked datasets at", time.strftime("%Y-%m-%d %H:%M:%S"))
        time.sleep(60)


if __name__ == "__main__":
    main()
