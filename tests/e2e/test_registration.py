"""Verify the pipeline -> backend registration handshake over the real
docker network: `pipeline/hohonu/pipeline.py`'s `build_defs()` POSTs its
config schema to the backend via `common.backend_api.BackendAPIClient`
(see docs/developer/index.md).
"""

import httpx
from conftest import wait_until
from dagster_graphql import DagsterGraphQLClient
from dagster_graphql.client.utils import ReloadRepositoryLocationStatus


def test_hohonu_location_loads_without_error(
    dagster_client: DagsterGraphQLClient,
) -> None:
    """The hohonu Dagster code location (re)loads without a PythonError.

    A successful reload means `build_defs()` ran to completion -- i.e.
    `register_pipeline()` reached the backend over the docker network and
    didn't raise. The reload (rather than just checking the boot-time load)
    is deliberate: the container boots as soon as `backend` is healthy,
    before the e2e_stack fixture has seeded the PipelineApiKey, so the
    *first* load always fails auth by design.
    """

    def _reload():
        try:
            info = dagster_client.reload_repository_location("hohonu")
        except Exception:  # noqa: BLE001 - transient during code-server startup, keep polling
            return None
        return info if info.status == ReloadRepositoryLocationStatus.SUCCESS else None

    info = wait_until(
        _reload,
        timeout=60,
        message="hohonu location to reload successfully",
    )
    assert info.status == ReloadRepositoryLocationStatus.SUCCESS


def test_pipeline_registered_with_backend(
    backend_client: httpx.Client,
) -> None:
    """The backend actually stored the POSTed registration.

    Complements the location-load test: a clean load proves the POST didn't
    raise, this proves the backend persisted a Pipeline row with the JSON
    Schema the frontend would render as a config form.
    """
    response = backend_client.get("pipelines/")
    response.raise_for_status()
    pipelines = {p["slug"]: p for p in response.json()}

    assert "hohonu" in pipelines, f"hohonu pipeline not registered: {pipelines}"
    hohonu = pipelines["hohonu"]
    assert hohonu["name"] == "Hohonu"
    assert hohonu["active"] is True
    assert "properties" in hohonu["config_schema"]
