# buoy_retriever

![Logo](./docs/logo.jpg)

IOOS Offshore Operations data management system

## Structure

This is setup as a mono-repo with a `backend/` Django server exposing Django-Ninja API endpoints and acting as a centeralized dataset configuration management system with Django's admin & auth systems for low level functionality.

Various `pipeline/`s report their capabilities into the Django backend, and retrieve dataset configurations for them to process. These will largely be implemented in Dagster, but there is the potential for other pipeline (AWS Lambda, Prefect, ...) to interact with the same backend and frontend.

Shared tooling will live in `common/` where they can be incorporated into the backend, pipelines, as well as potentially be published as a PyPI library that can be used in pipelines not included in this repo.

Most users (including RA/DAC admins) however, will be interacting with a Javascript `frontend/` which helps them configure their datasets based on the pipelines capabilities.

## Getting started

In `docker-data/secret.env` a few values need to be set before Django can be started

```
POSTGRES_PASSWORD=something_secret
POSTGRES_USER=buoy_retriever
POSTGRES_NAME=buoy_retriever
POSTGRES_HOST=db
BACKEND_SECRET_KEY=something_complex_and_random
```

Once the secret (/shared) values are set, `docker compose up --build backend` will start the database, cache, queue, and Django allowing for initial configuration.

The next steps are to create database tables with `make migrate` and then to create a superuser with `make user`.

Then to see the API docs go to http://localhost:8080/backend/api/docs/ and access the admin at http://localhost:8080/backend/admin/

I'd also suggest running `prek install` or `pre-commit install` to set up pre-commit hooks.

Once the migrations are run, the frontend and Dagster can be started with `make core`, though there won't be much functionality in either until one of the pipelines (I'd suggest Hohonu after adding an API key) is launched and has registered itself with the backend.

Pipelines will need an API key in order to access the backend.
Create it at http://localhost:8080/backend/admin/pipelines/pipelineapikey/
Django will auto-generate a key for you, but I'd suggest replacing it with `br_fake` to make testing easier.

The API key then can be added to `secret.env` as `BACKEND_API_KEY`.

Then `make core` to launch the backend, frontend, Dagster and supporting databases, while leaving individual pipelines for you to launch with `docker compose up --build <pipeline>`.

## Commands

- `make core` - Launch fronted, backend, Dagster, Spotlight, and other supporting services.
- `make up` - Launch all Docker services
- `make down` - Stop all Docker services
- `make migrations` - Generate new Django database migration files
- `make migrate` - run all Django database migrations
- `make prune` - Remove old Docker images and other debris hanging around
- `make shell` - Start a Python shell in the Django backend

## Services

- [`backend`](./backend/) - Django system administration with API via Django Ninja
- `db` - Timescale DB with PostGIS
- [`frontend`](./frontend/) - NextJS dataset management
- [`dagster_ui` and `dagster_daemon`](./pipeline/_dagster/) - Dagster pipeline orchastration

## Pipelines

Pipelines can be managed from [Dagster UI](http://localhost:3002).

Before they can be started, `BACKEND_API_KEY` needs to be set in `./docker-data/secret.env`.
This can be created from http://localhost:8080/backend/admin/pipelines/pipelineapikey/

### S3 Timeseries

[`s3_timeseries`](./pipeline/s3_timeseries/)

Requires `S3_TS_ACCESS_KEY_ID` and `S3_TS_SECRET_ACCESS_KEY` environment variables for S3 access.

### Hohonu

[`hohonu`](./pipeline/hohonu/)

Requires a `HOHONU_API_KEY` environment variable for API access.

### Aveva

[`aveva`](./pipeline/aveva/)

Requires `AVEVA_CLIENT_ID` and `AVEVA_CLIENT_SECRET` environment variables for API access.


## Development

For error handling, distributed tracing, and profiling, [Spotlight](https://spotlightjs.com/) by Sentry is setup and launches with `make up` or `make core` to http://localhost:8969/

Spotlight is also accessible to Github Copilot and other agents via a MCP server configuration.

### Testing

Currently there is some testing for common utilities and Hohonu pipelines.

`make test-all` to try to test everything.

- Common - `make test-common` or cd into `common/` then `uv run pytest`. Add `--cov=.` to see coverage (along with other pytest-cov options).
- Backend -  `make test-backend` with test some of the Django API server.
- Pipelines
  - S3 Timeseries - `make test-s3-timeseries` for more isolated tests, or `docker compose exec/run s3_timeseries pixi run pytest` which will mount volumes (in case snapshots need to be updated).
    - To run tests with real AWS data, include the `--aws` to `pytest`. This requires AWS credentials that can access the buckets.
  - Hohonu - `make test-hohonu` for a more isolated test, or  `docker compose exec/run hohonu pixi run pytest` will mount volumes (in case snapshots need to be updated).

Test data is stored in `docker-data/test-data`. This includes dataset configurations, which can be synced to and from the backend.

#### Snapshot Testing

`common/test_utils/snapshot.py` contains Pytest fixtures based on [pytest-regressions](https://pytest-regressions.readthedocs.io/en/latest/index.html) for snapshot testing that use our Dagster IO managers (to make that the formats we actually dump and load data are the same).

- `pandas_csv_regression.check(df, basename="test_daily_asset")`
- `nc_io_regression.check(ds, basename="test_monthly_asset", method="allclose")` (allows selecting which [Xarray test method](https://docs.xarray.dev/en/stable/api/testing.html)).

To use them:
- Add `pytest_plugins = ["common.test_utils.snapshot"]` to `conftest.py` or to the top of a test file.
- Create `lazy_datadir` and `original_datadir` fixtures to set where the files will be saved.
    ```py
    @pytest.fixture(scope="session")
    def lazy_datadir() -> Path:
        return TEST_DATA_DIR


    @pytest.fixture(scope="session")
    def original_datadir() -> Path:
        return TEST_DATA_DIR
    ```
- Call the fixture with `.check(<obj>, basename='extension-less path to check against')`. `test_kwargs={}` can also be added which will be passed to the underlying test method if it supports it.
- On the first run, they'll fail the test, but write out the file they got.
- If the file looks good, run the test again to validate that it passes, and add the file to the commit.

### Data management commands

There are several commands to help sync dataset configs to/from the backend for testing and development.

- View all datasets `docker compose exec backend pixi run ./manage.py list_datasets`
- Save a dataset and configs to disk `docker compose exec --user "$(id -u):$(id -g)" backend pixi run ./manage.py dump_dataset <dataset_id>`
- Load a dataset and configs back into the database `docker compose exec backend pixi run ./manage.py load_dataset <dataset_id>`.
  - It by default does a dry run so you can see what changes will be made. Add `--write` or `-w` to write out to a file.
  - The command searches through `docker-data/test-data` to find the matching dataset_id, but a path can be specified with `--input_path <INPUT_PATH>`

These can be used with the `DatasetBase.from_fixture()` method which takes a path to a dataset fixture, and the creation time (within a second to handle some time funkiness between systems) of a specific config to assemble a tested config from the Django database fixtures.

### Formatting/linting

Various formatters and linters are configured as pre-commit hooks and in Github Actions.

The linters and formatters defined in [.pre-commit-config.yaml](.pre-commit-config.yaml).

- General file validity/sanity checks from pre-commit-hooks
- Codespell
- Trailing commas (minimizes diffs)
- Bandit for security
- Gitleaks to make sure we don't check various tokens in
- Shellcheck for shell scripts
- Django Upgrade to apply Django standard practices
- PyProject format
- Ruff for general Python linting and checking (config in [ruff.toml](ruff.toml) but can be overridden or extended in subfolders via a local `ruff.toml` or `pyproject.toml`)
- Biome for general Javascript linting and checking (config in [biome.json](biome.json))

They can be manually run using [prek](https://prek.j178.dev/) (or [pre-commit](https://pre-commit.com/)) using `prek run --all-files`.

They will [automatically be run](https://prek.j178.dev/quickstart/#3-wire-hooks-into-git-automatically) when trying to `git commit` by running `prek install` once to set the repo up.
