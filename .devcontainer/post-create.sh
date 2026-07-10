#!/usr/bin/env bash
# Devcontainer post-create: fix volume ownership, install default envs, set up hooks.
# Run with --all to also install the four pipeline environments.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# Named volumes are created root-owned on first use
sudo chown -R vscode:vscode \
    backend/.pixi \
    pipeline/_dagster/.pixi \
    pipeline/aveva/.pixi \
    pipeline/hohonu/.pixi \
    pipeline/s3_timeseries/.pixi \
    common/.venv \
    frontend/node_modules \
    /home/vscode/.cache

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
