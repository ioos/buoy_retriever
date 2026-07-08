#syntax=docker/dockerfile:1.7
FROM ghcr.io/prefix-dev/pixi:0.43.3-jammy@sha256:a47be96e31621c1d2fbbfd41546acb96d8877622060782dd3405aacdbe495132

ENV PYTHON_USER ioos
ENV HOME /home/${PYTHON_USER}
ENV SOURCE ./pipeline/hohonu

# Output logging faster
ENV PYTHONUNBUFFERED 1
# Show deprecation warnings https://docs.djangoproject.com/en/2.2/howto/upgrade-version/#resolving-deprecation-warnings
ENV PYTHONWARNINGS once

ENV PIXI_FROZEN true

# Make the top-level modules (hohonu, hohonu_api, common) and the dg root
# module importable for the `dg` CLI and `code-server -m`, which do not add the
# working directory to sys.path the way `code-server -f script.py` did.
ENV PYTHONPATH ${HOME}

WORKDIR ${HOME}
COPY ${SOURCE}/pyproject.toml ${SOURCE}/pixi.lock ${HOME}/

RUN --mount=type=cache,id=br_hohonu,target=/home/ioos/.cache/rattler/cache,uid=1000,gid=1000 \
    pixi install -e default

COPY ./common/ ${HOME}/common/

RUN pixi shell-hook -e default > /shell-hook.sh \
    && echo 'exec "$@"' >> /shell-hook.sh

COPY ${SOURCE}/*.py \
    ${SOURCE}/*.jinja\
    ${SOURCE}/*.yaml \
    ${HOME}/

COPY ${SOURCE}/hohonu_defs/ ${HOME}/hohonu_defs/

COPY ${SOURCE}/tests/ ${HOME}/tests/

# COPY ${SOURCE}/platforms \
#     ${HOME}/platforms

ARG IMAGE_TAG
ENV IMAGE_TAG=${IMAGE_TAG:-unknown}

ENTRYPOINT ["/bin/bash", "/shell-hook.sh"]


# Refresh state-backed defs from the backend API (reachable only at runtime),
# then serve the cached definitions. Subsequent code-location reloads read the
# cached state instead of re-calling the API.
CMD [ "sh", "-c", "dg utils refresh-defs-state && exec dagster code-server start -p 4000 -m hohonu_defs.definitions -h 0.0.0.0" ]
