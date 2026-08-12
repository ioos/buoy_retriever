"""Verify a dataset config seeded in the backend's DB round-trips back to the
pipeline: the `boothbay_dmr_seeded` fixture (conftest.py) runs
`manage.py load_dataset` (the same tool a developer uses locally) and reloads
the hohonu code location, whose `build_defs()` then fetches the config back
via `BackendAPIClient.datasets_for_pipeline()` and turns it into Dagster
assets.
"""

import httpx
from conftest import Stack, dagster_graphql_url

ASSET_NODES_QUERY = """
query HohonuAssets {
  repositoryOrError(
    repositorySelector: {
      repositoryLocationName: "hohonu"
      repositoryName: "__repository__"
    }
  ) {
    __typename
    ... on Repository {
      assetNodes {
        assetKey {
          path
        }
        groupName
      }
    }
    ... on PythonError {
      message
    }
  }
}
"""


def test_seeded_config_returned_by_backend(
    boothbay_dmr_seeded: None,
    backend_client: httpx.Client,
) -> None:
    """The seeded config comes back from the by-pipeline endpoint.

    This is the exact endpoint `BackendAPIClient.datasets_for_pipeline()`
    calls, so it also exercises the backend's state filtering (only
    Testing/Published configs of Active datasets are returned).
    """
    response = backend_client.get("configs/by-pipeline/hohonu/")
    response.raise_for_status()
    configs = response.json()

    slugs = {c["slug"] for c in configs}
    assert "boothbay_dmr" in slugs, f"boothbay_dmr config not returned: {configs}"


def test_reloaded_location_builds_boothbay_dmr_assets(
    boothbay_dmr_seeded: None,
    e2e_stack: Stack,
) -> None:
    """The reloaded hohonu location turned the config into Dagster assets.

    Proves the pipeline side of the round trip: `build_defs()` fetched the
    seeded config via `datasets_for_pipeline()` and `defs_for_dataset()`
    produced an asset group named after the dataset slug.
    """
    result = httpx.post(
        dagster_graphql_url(e2e_stack),
        json={"query": ASSET_NODES_QUERY},
        timeout=30,
    )
    result.raise_for_status()
    payload = result.json()["data"]["repositoryOrError"]
    assert payload["__typename"] == "Repository", payload

    group_names = {node["groupName"] for node in payload["assetNodes"]}
    assert "boothbay_dmr" in group_names, group_names
