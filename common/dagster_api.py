"""
HTTP based client for interacting with Dagster's REST and GraphQL APIs.
"""

import os
from collections.abc import Sequence
from urllib.parse import urlparse

import httpx
from dagster_graphql import DagsterGraphQLClient
from pydantic import BaseModel, Field


def dagster_endpoint():
    """Parse the Dagster base URL from environment variable DAGSTER_BASE_URL or default to http://dagster_ui:3002"""
    dagster_base = os.environ.get("DAGSTER_BASE_URL", "http://dagster_ui:3002")
    return dagster_base


class DagsterAPICClient(BaseModel):
    """Integrated Dagster REST and GraphQL API client."""

    base_url: str = Field(default_factory=dagster_endpoint)
    repository: str = Field(description="The name of the Dagster repository")

    _graph_ql_client: DagsterGraphQLClient | None = None
    _http_client: httpx.Client | None = None

    def http_client(self) -> httpx.Client:
        """Get or create the HTTP client for interacting with Dagster."""
        if self._http_client is None:
            self._http_client = httpx.Client(base_url=self.base_url)
        return self._http_client

    def graphql_client(self) -> DagsterGraphQLClient:
        """Get or create the GraphQL client for interacting with Dagster."""
        if self._graph_ql_client is None:
            dagster_url = urlparse(self.base_url)
            self._graph_ql_client = DagsterGraphQLClient(
                dagster_url.hostname,
                port_number=dagster_url.port,
            )
        return self._graph_ql_client

    def reload_repo(self):
        """Reload the specified repository in Dagster."""
        self.graphql_client().reload_repository_location(self.repository)

    def materialize_assets_for_partitions(
        self,
        asset_keys: str | list[str] | list[list[str]],
        partitions: list[str],
    ) -> dict[str, str]:
        """Trigger materialization of the specified assets for multiple partitions.

        Returns a mapping of partition to run ID."""
        runs = {}

        for partition in partitions:
            run_id = self.materialize_assets(asset_keys, partition)
            runs[partition] = run_id

        return runs

    def materialize_assets(
        self,
        asset_keys: str | list[str] | list[list[str]],
        partition: str | None = None,
    ) -> str:
        """Trigger materialization of the specified assets, optionally for a given partition.

        Returns the run ID of the materialization."""
        tags = {}
        if partition:
            tags = {"dagster/partition": partition}

        run_id = self.graphql_client().submit_job_execution(
            "__ASSET_JOB",
            repository_location_name="hohonu",
            repository_name="__repository__",
            asset_selection=asset_keys,
            tags=tags,
        )
        return run_id

    def report_observation(
        self,
        asset_key: Sequence[str],
        last_modified: str,
        metadata: dict | None = None,
    ):
        """Report the observation of a source asset."""
        payload = {
            "asset_key": asset_key,
            "data_version": last_modified,
        }
        if metadata:
            payload["metadata"] = metadata

        self.http_client().post(
            "/report_asset_observation/",
            json=payload,
        ).raise_for_status()
