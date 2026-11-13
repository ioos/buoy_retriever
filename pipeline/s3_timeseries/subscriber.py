"""
Config subscriber for S3 timeseries datasets
"""

from s3_timeseries import PIPELINE_SLUG, S3TimeseriesDataset

from common.config.subscriber import Subscriber


class S3TimeseriesSubscriber(Subscriber):
    """Subscriber for S3 timeseries datasets."""

    dataset_type: type[S3TimeseriesDataset] = S3TimeseriesDataset
    pipeline_slug: str = PIPELINE_SLUG

    def new_config(self, dataset: S3TimeseriesDataset):
        """Handle new configuration for the dataset."""
        print(f"New configuration for dataset: {dataset.slug}")
        super().new_config(dataset)


if __name__ == "__main__":
    S3TimeseriesSubscriber().subscribe_loop()
