#!/usr/bin/env bash
# Devcontainer post-create: fix volume ownership, install default envs, set up hooks.
# Run with --all to also install the four pipeline environments.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Named volumes (local config) are created root-owned on first use. In the
# Codespaces config there are no volumes, so these paths don't exist yet -
# the installs below create them with the right ownership.
for path in \
    backend/.pixi \
    pipeline/_dagster/.pixi \
    pipeline/aveva/.pixi \
    pipeline/hohonu/.pixi \
    pipeline/s3_timeseries/.pixi \
    common/.venv \
    frontend/node_modules \
    /home/vscode/.cache; do
    if [ -e "$path" ]; then
        sudo chown -R vscode:vscode "$path"
    fi
done

# Trust the workspace mise.toml so interactive shells don't prompt
mise trust mise.toml

if [ ! -f docker-data/secret.env ]; then
    echo "WARNING: docker-data/secret.env is missing - docker compose services will not start."
    echo "  Generate it on the host from 1Password, or see .devcontainer/README.md for Codespaces."
fi

prek install

# Fast path: the projects most sessions touch.
# --frozen everywhere: never rewrite lockfiles during setup.
(cd backend && pixi install --frozen -e dev)
(cd common && uv sync)
(cd frontend && npm ci)

if [ "${1:-}" = "--all" ]; then
    for project in pipeline/aveva pipeline/hohonu pipeline/s3_timeseries; do
        (cd "$project" && pixi install --frozen -e dev)
    done
    # pipeline/_dagster has no "dev" environment defined (no [environments] table
    # in its pixi.toml) - install its single default environment instead.
    (cd pipeline/_dagster && pixi install --frozen)
else
    echo "Pipeline envs not installed (saves several minutes)."
    echo "  To install them: bash .devcontainer/post-create.sh --all"
fi
