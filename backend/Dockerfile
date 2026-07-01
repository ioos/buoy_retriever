FROM ghcr.io/prefix-dev/pixi:0.66.0@sha256:e8857b9ba407f92958feb0098c816cae713264251d43bb42217bcedfc8a719fd AS base

# Gather required base utils
RUN apt-get update && apt-get install -y \
        curl \
        && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Output logging faster
ENV PYTHONUNBUFFERED=1
# Show deprecation warnings https://docs.djangoproject.com/en/2.2/howto/upgrade-version/#resolving-deprecation-warnings
ENV PYTHONWARNINGS=once

# User variables
ENV USER=uwsgi
ENV USER_HOME="/home/${USER}"
ENV APP_DIR="/home/${USER}/app"
ENV USER_UID=1001
ENV PIXI_HOME="${USER_HOME}/.pixi"

# Setup user
RUN groupadd ${USER} \
    && useradd -rm -d ${USER_HOME} -s /bin/bash -g ${USER} -u ${USER_UID} ${USER}
RUN mkdir -p /static /media /support ${APP_DIR} /opt/pixi/envs
RUN chown -R ${USER}:${USER} ${USER_HOME} /static /media /support ${APP_DIR} /opt/pixi/envs

USER ${USER}
WORKDIR ${APP_DIR}

# Copy only env spec and build
COPY --chown=${USER}:${USER} ./pyproject.toml ./pixi.lock ${APP_DIR}
RUN --mount=type=cache,id=br_pixi,target=${USER_HOME}/.cache/rattler/cache,uid=${USER_UID},gid=${USER_UID} \
    pixi config set --global detached-environments "/opt/pixi/envs" \
    && pixi install -e default --frozen

# Copy app source (and only app source)
COPY --chown=${USER}:${USER} ./*.py ${APP_DIR}/
COPY --chown=${USER}:${USER} ./account ${APP_DIR}/account
COPY --chown=${USER}:${USER} ./buoy_retriever ${APP_DIR}/buoy_retriever
COPY --chown=${USER}:${USER} ./datasets ${APP_DIR}/datasets
COPY --chown=${USER}:${USER} ./pipelines ${APP_DIR}/pipelines
COPY --chown=${USER}:${USER} ./ninja_postgrest ${APP_DIR}/ninja_postgrest

RUN echo '#!/bin/bash' > /support/shell-hook.sh \
    && pixi shell-hook -e default --shell bash | grep -vie "activate.d" | grep -vie "completion" >> /support/shell-hook.sh \
    && echo 'exec "$@"' >> /support/shell-hook.sh \
    && chmod +x /support/shell-hook.sh

ARG IMAGE_TAG
ENV IMAGE_TAG=${IMAGE_TAG:-unknown}

ENTRYPOINT ["/support/shell-hook.sh"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s \
    CMD /usr/bin/curl -D- -o /dev/null --silent --fail "http://localhost:8080/backend/health/"


FROM base AS develop

RUN --mount=type=cache,id=br_pixi,target=${USER_HOME}/.cache/rattler/cache,uid=${USER_UID},gid=${USER_UID} \
    pixi install -e dev


# FROM base AS deploy

# COPY --chown=${USER}:${USER} . ${USER_HOME}
# CMD ["uwsgi"l]
