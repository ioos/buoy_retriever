from typing import Annotated

import httpx
import sentry_sdk
from pydantic import BaseModel, Field, ValidationError

from .config import DatasetBase, PipelineConfig


def api_client_key():
    """Retrieve the backend API key from environment variable"""
    import os

    api_key = os.environ["BACKEND_API_KEY"]
    return api_key


class BackendAPIClient(BaseModel):
    api_endpoint: str = "http://backend:8080/backend/api/"
    api_key: Annotated[
        str,
        Field(
            description="API key for authenticating with backend API",
            default_factory=api_client_key,
        ),
    ]
    timeout: Annotated[
        int,
        Field(
            description="Default seconds before timing out connecting to backend API",
        ),
    ] = 30

    def headers(self):
        """Add API key to headers"""
        return {"X-API-KEY": self.api_key}

    def register_pipeline(self, pipeline: PipelineConfig):
        """Create or update a pipeline configuration"""
        with sentry_sdk.start_span(
            op="register_pipeline",
            name=f"Register pipeline {pipeline.slug}",
        ):
            json = pipeline.to_json()

            url = self.api_endpoint + "pipelines/"

            result = httpx.post(
                url,
                json=json,
                timeout=self.timeout,
                headers=self.headers(),
            )
            result.raise_for_status()

            return result.json()

    def raw_datasets_for_pipeline(self, pipeline_slug: str) -> list[dict]:
        """Get raw (unvalidated) dataset config dicts for a pipeline slug.

        Used by state-backed components, which persist the raw API response and
        validate it into dataset models later when building definitions.
        """
        with sentry_sdk.start_span(
            op="raw_datasets_for_pipeline",
            name=f"Get raw datasets for pipeline {pipeline_slug}",
        ):
            url = self.api_endpoint + f"configs/by-pipeline/{pipeline_slug}/"

            result = httpx.get(
                url,
                timeout=self.timeout,
                headers=self.headers(),
            )
            result.raise_for_status()

            return result.json()

    def datasets_for_pipeline(
        self,
        pipeline_slug: str,
        dataset_model: type[DatasetBase],
    ):
        """Get datasets for a given pipeline slug"""
        with sentry_sdk.start_span(
            op="datasets_for_pipeline",
            name=f"Get datasets for pipeline {pipeline_slug}",
        ):
            datasets_json = self.raw_datasets_for_pipeline(pipeline_slug)

            datasets = []

            for d in datasets_json:
                try:
                    dataset = dataset_model(**d)
                except ValidationError as e:
                    print(f"Error validating dataset {d}: {e}")
                    print(
                        "Post back to message API about error parsing the dataset configuration",
                    )
                    continue
                datasets.append(dataset)

            return datasets
