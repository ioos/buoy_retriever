"""Stack lifecycle for the end-to-end connectivity suite.

Brings up an isolated docker compose stack (docker-compose.yaml +
docker-compose.e2e.yaml, project "buoy_retriever_e2e") covering the real
pipeline registration handshake: db -> backend -> hohonu (Dagster code
location) -> dagster_daemon/dagster_ui.

See docs/developer/index.md for the handshake this suite exercises, and
docker-compose.e2e.yaml for why this stack is isolated from a developer's
dev stack (fresh DB, mocked secrets, remapped ports, built images only).
"""

import os
import shutil
import subprocess
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from dagster_graphql import DagsterGraphQLClient
from dagster_graphql.client.utils import ReloadRepositoryLocationStatus

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILES = ("-f", "docker-compose.yaml", "-f", "docker-compose.e2e.yaml")
COMPOSE_PROJECT = "buoy_retriever_e2e"
COMPOSE_SERVICES = (
    "db",
    "backend",
    "dagster_postgres",
    "dagster_daemon",
    "dagster_ui",
    "hohonu",
)

# Must match docker-data/secret.e2e.env and docker-compose.e2e.yaml's port overrides.
BACKEND_PORT = int(os.environ.get("BUOY_RETRIEVER_E2E_BACKEND_PORT", "18080"))
DAGSTER_UI_PORT = int(os.environ.get("BUOY_RETRIEVER_E2E_DAGSTER_UI_PORT", "13002"))
BACKEND_API_KEY = "br_e2e_fake"

SEED_API_KEY_SCRIPT = f"""
from django.contrib.auth import get_user_model
from pipelines.models import PipelineApiKey

User = get_user_model()
user, _ = User.objects.get_or_create(username="e2e", defaults={{"is_staff": True}})
PipelineApiKey.objects.get_or_create(
    key_value={BACKEND_API_KEY!r},
    defaults={{"user": user, "name": "e2e"}},
)
""".strip()


@dataclass(frozen=True)
class Stack:
    """Handles for the running e2e stack, as seen from the host."""

    backend_url: str
    backend_api_key: str
    dagster_hostname: str
    dagster_port: int
    shared_fs_dir: Path


def _compose(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", "compose", *COMPOSE_FILES, "-p", COMPOSE_PROJECT, *args],
        cwd=REPO_ROOT,
        check=check,
        capture_output=True,
        text=True,
    )


def _teardown() -> None:
    _compose("down", "-v", "--remove-orphans", check=False)


@pytest.fixture(scope="session")
def shared_fs_dir() -> Iterator[Path]:
    """Per-run temporary shared-fs output directory.

    docker-compose.e2e.yaml mounts $BUOY_RETRIEVER_E2E_SHARED_FS at
    /mnt/efs/, so giving every session a fresh directory (rather than the
    fixed docker-data/shared-fs-e2e path) means output from a previous run
    can never satisfy this run's assertions, with no manual cleanup.

    Host-side cleanup is strictly best-effort: on Linux the containers
    write output as their own uid, which the CI runner's user may not be
    able to delete (Python 3.12's TemporaryDirectory raises on this even
    with ignore_cleanup_errors=True, failing the last test's teardown).
    The e2e_stack fixture already deletes the output from *inside* the
    container -- which owns the files -- before the stack goes down, so
    this rmtree normally only removes an empty tree; if anything survives,
    leaking a gitignored temp dir on an ephemeral runner is harmless. With
    E2E_KEEP_STACK=1 the directory is kept too -- deleting it out from
    under the still-running stack would discard exactly the output the
    stack was kept to inspect.
    """
    parent = REPO_ROOT / "docker-data" / "shared-fs-e2e"
    parent.mkdir(parents=True, exist_ok=True)

    tmp = tempfile.mkdtemp(dir=parent, prefix="run-")
    os.environ["BUOY_RETRIEVER_E2E_SHARED_FS"] = tmp
    yield Path(tmp)
    if os.environ.get("E2E_KEEP_STACK") != "1":
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture(scope="session")
def e2e_stack(shared_fs_dir: Path) -> Iterator[Stack]:
    keep_stack = os.environ.get("E2E_KEEP_STACK") == "1"

    # Always start from a clean slate: a crashed prior run may have left the
    # project's volumes (and therefore its DB state) behind.
    _teardown()
    try:
        up = _compose(
            "up",
            "-d",
            "--build",
            "--wait",
            *COMPOSE_SERVICES,
            check=False,
        )
        if up.returncode != 0:
            logs = _compose("logs", "--no-color", check=False).stdout
            msg = f"docker compose up failed:\n{up.stdout}\n{up.stderr}\n\n{logs}"
            raise RuntimeError(msg)

        migrate = _compose(
            "exec",
            "-T",
            "backend",
            "pixi",
            "run",
            "python",
            "manage.py",
            "migrate",
            check=False,
        )
        if migrate.returncode != 0:
            msg = f"manage.py migrate failed:\n{migrate.stdout}\n{migrate.stderr}"
            raise RuntimeError(msg)

        seed = _compose(
            "exec",
            "-T",
            "backend",
            "pixi",
            "run",
            "python",
            "manage.py",
            "shell",
            "-c",
            SEED_API_KEY_SCRIPT,
            check=False,
        )
        if seed.returncode != 0:
            msg = f"seeding PipelineApiKey failed:\n{seed.stdout}\n{seed.stderr}"
            raise RuntimeError(msg)

        # hohonu's code server booted before the PipelineApiKey existed (it
        # only depends on `backend` being healthy), so its first
        # register_pipeline() attempt failed auth. Reload now that the key
        # exists so every test file can assume the pipeline is already
        # registered, regardless of collection order.
        graphql_url = f"http://localhost:{DAGSTER_UI_PORT}/graphql"

        def _initial_reload():
            try:
                response = httpx.post(
                    graphql_url,
                    json={
                        "query": (
                            "mutation { reloadRepositoryLocation("
                            'repositoryLocationName: "hohonu") { __typename '
                            "... on WorkspaceLocationEntry { locationOrLoadError { "
                            "__typename ... on PythonError { message } } } } }"
                        ),
                    },
                    timeout=30,
                )
                response.raise_for_status()
                location = response.json()["data"]["reloadRepositoryLocation"][
                    "locationOrLoadError"
                ]
            except httpx.HTTPError:
                return None
            return location if location["__typename"] == "RepositoryLocation" else None

        wait_until(
            _initial_reload,
            timeout=60,
            message="hohonu location to register with backend",
        )

        yield Stack(
            backend_url=f"http://localhost:{BACKEND_PORT}/backend/api/",
            backend_api_key=BACKEND_API_KEY,
            dagster_hostname="localhost",
            dagster_port=DAGSTER_UI_PORT,
            shared_fs_dir=shared_fs_dir,
        )
    finally:
        if not keep_stack:
            # Delete run output from inside the container before the stack
            # goes down: the container owns those files, and on Linux the
            # host user often can't (see the shared_fs_dir fixture).
            _compose(
                "exec",
                "-T",
                "hohonu",
                "bash",
                "-c",
                "rm -rf /mnt/efs/* 2>/dev/null || true",
                check=False,
            )
            _teardown()


@pytest.fixture(scope="session")
def backend_client(e2e_stack: Stack) -> Iterator[httpx.Client]:
    with httpx.Client(
        base_url=e2e_stack.backend_url,
        headers={"X-API-KEY": e2e_stack.backend_api_key},
        timeout=30,
    ) as client:
        yield client


@pytest.fixture(scope="session")
def dagster_client(e2e_stack: Stack) -> DagsterGraphQLClient:
    return DagsterGraphQLClient(
        e2e_stack.dagster_hostname,
        port_number=e2e_stack.dagster_port,
    )


@pytest.fixture(scope="session")
def boothbay_dmr_seeded(
    e2e_stack: Stack,
    dagster_client: DagsterGraphQLClient,
) -> None:
    """Seed the boothbay_dmr dataset config and reload the hohonu location
    so its Dagster assets/jobs exist.

    Session-scoped so any test file can depend on it without relying on
    another test file having run first (pytest collects files
    alphabetically, which happens to work, but is not an ordering
    guarantee).
    """
    seed = _compose(
        "exec",
        "-T",
        "backend",
        "pixi",
        "run",
        "python",
        "manage.py",
        "load_dataset",
        "boothbay_dmr",
        "--write",
        check=False,
    )
    if seed.returncode != 0:
        msg = f"load_dataset failed:\n{seed.stdout}\n{seed.stderr}"
        raise RuntimeError(msg)

    def _reload():
        try:
            info = dagster_client.reload_repository_location("hohonu")
        except Exception:  # noqa: BLE001 - transient during code-server restart, keep polling
            return None
        return info if info.status == ReloadRepositoryLocationStatus.SUCCESS else None

    wait_until(
        _reload,
        timeout=60,
        message="hohonu location to reload with the seeded config",
    )


def dagster_graphql_url(stack: Stack) -> str:
    """Raw GraphQL endpoint, for queries DagsterGraphQLClient doesn't wrap."""
    return f"http://{stack.dagster_hostname}:{stack.dagster_port}/graphql"


def wait_until(
    predicate,
    *,
    timeout: float = 60,
    interval: float = 2,
    message: str = "condition",
):
    """Poll `predicate` (no-arg callable returning a truthy value) until it
    succeeds or `timeout` elapses, returning the truthy value."""
    deadline = time.monotonic() + timeout
    last_result = None
    while time.monotonic() < deadline:
        last_result = predicate()
        if last_result:
            return last_result
        time.sleep(interval)
    msg = f"Timed out after {timeout}s waiting for {message}"
    raise TimeoutError(msg)
