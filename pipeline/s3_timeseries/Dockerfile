#syntax=docker/dockerfile:1.7
FROM ghcr.io/prefix-dev/pixi:0.43.3-jammy@sha256:a47be96e31621c1d2fbbfd41546acb96d8877622060782dd3405aacdbe495132

ENV PYTHON_USER ioos
ENV HOME /home/${PYTHON_USER}
ENV SOURCE ./pipeline/s3_timeseries

# Output logging faster
ENV PYTHONUNBUFFERED 1
# Show deprecation warnings https://docs.djangoproject.com/en/2.2/howto/upgrade-version/#resolving-deprecation-warnings
ENV PYTHONWARNINGS once

ENV PIXI_FROZEN true

WORKDIR ${HOME}
COPY ${SOURCE}/pyproject.toml ${SOURCE}/pixi.lock ${HOME}/

RUN --mount=type=cache,id=br_s3_timeseries,target=/home/ioos/.cache/rattler/cache,uid=1000,gid=1000 \
    pixi install -e default

COPY ./common/ ${HOME}/common/

RUN pixi shell-hook -e default > /shell-hook.sh \
    && echo 'exec "$@"' >> /shell-hook.sh

COPY ${SOURCE}/*.py \
    ${SOURCE}/*.jinja\
    ${SOURCE}/*.yaml \
    ${SOURCE}/.coveragerc \
    ${HOME}/


COPY ${SOURCE}/tests/ ${HOME}/tests/

ARG IMAGE_TAG
ENV IMAGE_TAG=${IMAGE_TAG:-unknown}

ENTRYPOINT ["/bin/bash", "/shell-hook.sh"]

# placeholder test metadata until we are retrieving metadata from
# asset manager via Django API
ENV METADATA_PATH=/mnt/test-data/s3_timeseries/metadata


CMD [ "dagster", "code-server", "start", "-p", "4000", "-f", "pipeline.py", "-h", "0.0.0.0" ]
