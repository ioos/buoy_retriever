# Build all Docker compose services
build:
	docker compose build

# Start all services. Most likely want to use `make core` instead
# and then start specific pipelines as needed.
up: down build
	# docker compose up --watch
	docker compose up

# Start core services: backend, frontend, dagster_ui, dagster_daemon
core:
	docker compose up --build backend frontend dagster_ui dagster_daemon

# Start up spotlight to catch errors and traces from services
spotlight:
	docker compose run --rm spotlight

# Stop and remove all containers
down:
	docker compose -f docker-compose.yaml down --remove-orphans

# Stop all containers without removing them
stop:
	docker compose stop

# View real-time logs for all services
logs:
	docker compose logs -f

# Run all pending migrations
migrations:
	docker compose exec backend pixi run python manage.py makemigrations

# Create a blank migration file inside the backend container
blank-migration:
	# docker compose exec backend pixi run python manage.py makemigrations -n tide_data_types --empty deployments
	docker compose exec backend pixi run python manage.py makemigrations --empty deployments

# Auto generate migrations for any model changes
migrate:
	docker compose exec backend pixi run python manage.py migrate

# Cleanup unused Docker resources
prune:
	docker volume rm $(shell docker volume ls -qf dangling=true)
	docker buildx prune -f
	docker system prune --volumes
	docker system prune -a

# Create a superuser inside the backend container
user:
	docker compose exec backend pixi run python manage.py createsuperuser

# Open a Django shell inside the backend container
shell:
	docker compose exec backend pixi run python manage.py shell

test-common:
	cd common; uv run pytest --cov=.

test-backend:
	docker build -t buoy_retriever-backend backend/
	docker run -v ./docker-data/test-data:/mnt/test-data:ro buoy_retriever-backend pixi run pytest --cov=.

test-hohonu:
	docker build -f pipeline/hohonu/Dockerfile -t buoy_retriever-hohonu .
	docker run -v ./docker-data/test-data:/mnt/test-data buoy_retriever-hohonu pixi run pytest --cov=.

test-s3-timeseries:
	docker build -f pipeline/s3_timeseries/Dockerfile -t buoy_retriever-s3_timeseries .
	docker run -v ./docker-data/test-data:/mnt/test-data buoy_retriever-s3_timeseries pixi run pytest --cov=.

e2e_compose_command = docker compose -f docker-compose.yaml -f docker-compose.e2e.yaml -p buoy_retriever_e2e
e2e_build_containers = backend dagster_daemon dagster_ui hohonu

# Build the e2e containers
e2e-build:
	$(e2e_compose_command) build $(e2e_build_containers)

# Run the end-to-end connectivity suite (spins up an isolated docker-compose
# stack; see tests/e2e/conftest.py and docker-compose.e2e.yaml).
# --no-install-project: the suite doesn't import the root scaffold package,
# so don't require src/buoy_retriever to exist/build.
test-e2e: e2e-build
	uv sync --group e2e --no-install-project
	uv run --no-sync pytest tests/e2e -v

# Bring up the e2e stack and leave it running (for local debugging: set
# E2E_KEEP_STACK=1 so the test suite's teardown doesn't tear it down)
e2e-up: e2e-build
	$(e2e_compose_command) up -d --wait db dagster_postgres $(e2e_build_containers)

# Tear down the e2e stack and remove its volumes
e2e-down:
	$(e2e_compose_command) down -v --remove-orphans

test-all: test-common test-backend test-s3-timeseries test-hohonu test-aveva test-e2e
