---
icon: lucide/network
---

# End-to-end connectivity tests

`tests/e2e/` exercises the
[pipeline registration handshake](./index.md#the-pipeline-registration-handshake)
against a multi-container stack: a live Django backend with a
Postgres database, a Dagster pipeline (Hohonu), and the
Docker network between them. Everything else in the repo tests one
component at a time (VCR cassettes for API calls, `moto` for S3, fixtures
for Dagster defs) — this suite is what proves the pieces can communicate.

## What it covers

The suite is three test files that focus on different aspects of the system. Conceptually they build on
each other, but each is self-sufficient — the shared setup (stack boot, API
key seeding, `boothbay_dmr` config seeding + location reload) lives in
session-scoped fixtures in `conftest.py`, so any file can be run on its own
and actual collection order doesn't matter:

- **`test_registration.py`** — tests that the `hohonu` code location loads without
  error (its `build_defs()` POSTs the config schema via
  `BackendAPIClient.register_pipeline()`), and the backend's
  `/backend/api/pipelines/` endpoint shows the stored schema.
- **`test_config_roundtrip.py`** — after the `boothbay_dmr_seeded` fixture
  runs `manage.py load_dataset boothbay_dmr --write` (the same fixture file
  and command a developer uses locally), the
  `/backend/api/configs/by-pipeline/hohonu/` endpoint returns the config,
  and the reloaded location exposes its Dagster assets.
- **`test_ingest.py`** — the daily and monthly asset jobs are launched
  through the Dagster GraphQL API, and the resulting NetCDF is opened
  from the shared filesystem volume and spot-checked (variable name and
  CF `standard_name`).

## Running it

```bash
make test-e2e          # or: uv run --group e2e pytest tests/e2e -v
```

Requirements: Docker, and the root project's `e2e` dependency group
(`uv sync --group e2e`; `uv run --group e2e` handles this automatically).
No real credentials of any kind — see "How it stays hermetic" below.

The suite manages its own stack lifecycle: `tests/e2e/conftest.py` tears
down any leftover state, builds and starts the services, runs Django
migrations, seeds a `PipelineApiKey`, and tears everything down again at
the end. A full run takes about a minute once images are cached.

For debugging, keep the stack up after the run:

```bash
E2E_KEEP_STACK=1 uv run --group e2e pytest tests/e2e -v
make e2e-down          # tear it down when you're finished
```

`make e2e-up` starts the stack without running tests (the Dagster UI is on
port 13002, the backend on 18080 — see below).

## How the stack is isolated

`docker-compose.e2e.yaml` is a compose override applied on top of the dev
`docker-compose.yaml`, under a separate project name (`buoy_retriever_e2e`)
so it can run alongside a developer's `make core` stack:

- **Fresh database every run** — the Postgres bind mounts are replaced with
  anonymous volumes, and the suite runs `docker compose down -v` before
  *and* after, so no state leaks between runs (or in from your dev stack).
- **Committed placeholder secrets** — `docker-data/secret.e2e.env` replaces
  the gitignored `docker-data/secret.env`. Every value in it is throwaway;
  nothing real is needed.
- **Remapped ports** — backend `18080`, Dagster UI `13002`, databases
  `15432`/`15433` (all overridable via `BUOY_RETRIEVER_E2E_*_PORT`), so
  nothing collides with the dev stack's defaults.
- **Built images, not live source** — the dev stack's source bind mounts
  are dropped, so the suite exercises what's actually baked into the
  Docker images. The mounts that remain (test data, fixture cassettes,
  Dagster workspace config, the VCR shim) are read-only; only the
  shared-fs output volume is writable.
- **Per-run output directory** — the shared-fs mount points at a fresh
  `tempfile.TemporaryDirectory` under `docker-data/shared-fs-e2e/`
  (`$BUOY_RETRIEVER_E2E_SHARED_FS`), so output from one run can never
  satisfy another run's assertions, and it cleans itself up (kept, along
  with the stack, under `E2E_KEEP_STACK=1`).

### How it stays hermetic (no Hohonu credentials)

The Hohonu API base URL is hardcoded in `pipeline/hohonu/hohonu_api.py`, so
instead of a stub server, the override bind-mounts
`pipeline/hohonu/e2e_sitecustomize.py` into the `hohonu` container **as**
`/home/ioos/sitecustomize.py` and sets `PYTHONPATH=/home/ioos`. Python then
auto-imports it in **every** process in that container — the code server,
the run process, and step workers alike. That shim wraps `requests.get` so
each call to `dashboard.hohonu.io` is replayed from the *existing*
`test_daily_asset.yaml` VCR cassette (the same one the unit tests use).

The `e2e_` name on disk is deliberate: Python only auto-imports a module
named exactly `sitecustomize`, and the file is also excluded from Docker
build contexts via `.dockerignore`, so it cannot end up active (or even
present) in a dev or production image — only the e2e override's mount
creates a real `sitecustomize.py`.

Two details, if you ever need to touch this:

- The shim wraps `requests.get` per-call rather than holding one
  `vcr.use_cassette()` context open for the process lifetime — Dagster's
  definition-loading/run machinery was observed restoring vcrpy's patched
  HTTP classes mid-process, silently letting requests through to the real
  API.
- `test_ingest.py` launches runs with the in-process executor
  (`run_config={"execution": {"config": {"in_process": {}}}}`) because the
  default multiprocess executor spawns step workers with `-S -E`, which
  skips `site` processing entirely — the exact mechanism the shim relies
  on.

### Why the API key has to be seeded

`BACKEND_API_KEY` is not enough by itself: the backend authenticates
pipelines against `PipelineApiKey` **database rows**
(`backend/pipelines/api.py`), which on a fresh database don't exist. The
conftest seeds one matching the placeholder key after migrations, then
reloads the `hohonu` code location — its first registration attempt at
container boot fails auth by design, since the container only waits for the
backend's health check, not for seeding.

## CI

`.github/workflows/e2e.yml` runs the suite on pull requests and pushes to
`main` that touch `backend/`, `common/`, `pipeline/hohonu/`,
`pipeline/_dagster/`, the compose files, or the suite itself. On failure it
dumps the full compose logs into the Actions log before tearing down.

## Maintenance notes

Things most likely to break this suite, and what to do about them:

- **Cassette drift.** The shim replays with `record_mode="none"` against
  one cassette recorded for station `hohonu-169` on `2025-09-30`. Any
  change to `HohonuApi.load_daily_data`'s URL or query params, to the
  `boothbay_dmr.json` fixture, or to the cassette itself breaks replay,
  and shows up as a *real-API 401* in the ingest test (the placeholder key
  is `FAKE`, so nothing real is ever hit successfully). To re-record: run
  the hohonu unit suite with a real `HOHONU_API_KEY` and
  `--record-mode=once` (the normal `pytest-recording` flow), then update
  the partition-key constants at the top of `test_ingest.py` if the
  recorded dates changed.
- **The two oddities.** The per-call `requests.get` wrapper
  and the in-process executor (see above) both look like they could be
  simplified. They can't — both were forced by observed Dagster behavior,
  and regressing either produces the same confusing real-API 401.
- **A 401 in `test_ingest.py` almost always means the shim isn't active**
  for the failing process (cassette mismatch, executor changed, mount
  missing) — check there before suspecting credentials.
- **Stale images.** The suite tests built images, not your working tree.
  `--build` is passed on every run, but if a code change doesn't seem to
  take effect, suspect Docker layer caching before suspecting the test.
- **Concurrent runs collide.** The compose project name is fixed
  (`buoy_retriever_e2e`), so two simultaneous runs on the same machine
  fight over containers and volumes. Ports are overridable
  (`BUOY_RETRIEVER_E2E_*_PORT`); the project name is not. Fine on
  GitHub-hosted runners; a hazard on a shared self-hosted runner.
- **Timeouts.** Waits are generous (60s reload / 180s per run) and a warm
  run takes ~1 minute, but a cold CI runner builds three images first — on
  a CI timeout, check image build time in the logs before blaming a test.
- **Warning filters.** Two `filterwarnings` ignores in the root
  `pyproject.toml` (gql's deprecation warning inside `dagster-graphql`,
  netCDF4's numpy-ABI import warning) exist solely for this suite; under
  the scaffold's `filterwarnings = "error"` regime, removing them
  re-breaks the suite in non-obvious ways.
