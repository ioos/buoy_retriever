# Devcontainer

A single devcontainer for the whole monorepo: the Django `backend`, the `common` library,
the `frontend` Next.js app, and the four `pipeline/*` Dagster projects.

## Quickstart (local)

Prerequisites:

- Docker Desktop
- VS Code with the "Dev Containers" extension
- `docker-data/secret.env`, generated from 1Password, created on the **host** before you
  open the container. The compose services need it to start; the container itself will only
  warn (not fail) if it is missing.

With those in place, open the repo in VS Code and run "Dev Containers: Reopen in Container".
The first build/create takes about 3-6 minutes while it installs the backend pixi env, runs
`uv sync` for `common`, and runs `npm ci` for the frontend. Rebuilds after that are fast
because those environments live on named Docker volumes, not in the image or the bind-mounted
workspace.

The four `pipeline/*` project environments are opt-in, since most sessions don't need all of
them and installing every one adds several minutes. Install them on demand with:

```bash
bash .devcontainer/post-create.sh --all
```

## How it works

There is one container for the entire monorepo rather than one per service. The toolchain
(Node, pixi, uv, prek) is version-pinned in the root `mise.toml` and baked into the devcontainer
image at build time via [mise](https://mise.jdx.dev/), so every tool version matches what CI and
your teammates use.

Docker access is docker-outside-of-docker: the devcontainer gets the host's Docker socket
rather than running its own nested daemon, so `make` and `docker compose` commands inside the
container drive the same daemon as your host. Because compose's bind mounts (`./backend`,
`./docker-data`, etc.) are relative to the compose file, the workspace is mounted at its exact
host path inside the container - otherwise those relative paths would resolve incorrectly
against the host daemon.

One consequence: ports published by `docker compose` (backend, frontend, Dagster UI, Postgres,
...) show up on the **host's** localhost (e.g. `http://localhost:8080`), not inside the
devcontainer itself. If you need to reach one of those ports from a shell inside the
devcontainer, use `host.docker.internal:<port>` instead of `localhost:<port>`.

## Claude Code

The host's `~/.claude` directory and `~/.claude.json` file are bind-mounted into the container,
so your Claude Code authentication, settings, and memory carry over automatically. Both paths
must already exist on the host before you first open the container - if they don't, Docker will
create them itself, and it creates `~/.claude.json` as a root-owned **directory**, which breaks
Claude Code. If you've never run Claude Code locally, `touch ~/.claude.json` and
`mkdir -p ~/.claude` on the host first.

## Codespaces

When creating a codespace, choose "New with options..." and select the
"buoy_retriever (Codespaces)" devcontainer configuration. Codespaces has no host Docker daemon
to share, so this variant uses docker-in-docker instead of docker-outside-of-docker, and it
skips the local-only workspace mount override, named volumes, and Claude Code bind mounts.

You'll still need `docker-data/secret.env` for the compose services to start; create it
manually inside the codespace from your Codespaces secrets, or populate it with local
development defaults. Forwarded ports appear through the Codespaces "Ports" panel rather than
on `localhost`.

## Agent sandboxing

Running an agent (such as Claude Code) inside the default local devcontainer gives you a
contained, version-pinned toolchain, but it is not a security boundary. Docker-outside-of-docker
hands the container the host's Docker socket, and access to that socket is root-equivalent on
the host - an agent (or anything it runs) can use it to affect the host well beyond the
container. Treat the default config as workflow isolation only. If you need stronger sandboxing
for an agent running locally, use the codespaces (docker-in-docker) configuration instead, since
it never has access to the host daemon.

## Notes / gotchas

- The image pins pixi 0.66.0, which is newer than the pixi version used to generate the
  existing `pipeline/*` lockfiles. Setup always installs with `--frozen` so those lockfiles are
  never silently rewritten. Don't run `pixi update` inside a pipeline project unless you
  specifically intend to migrate its lockfile to the newer pixi.
- The named volumes (`buoy-retriever-*`) shadow `.pixi`, `.venv`, and `node_modules` directories
  only inside the devcontainer; they have no effect on the host checkout. If you want a
  completely clean environment, remove them with `docker volume rm` and let post-create
  reinstall from scratch.
