FROM mcr.microsoft.com/devcontainers/base:ubuntu-24.04

COPY --from=ghcr.io/jdx/mise:2026.4.18 /usr/local/bin/mise /usr/local/bin/mise

# Bake the repo-pinned toolchain (node, pixi, uv, prek) into the image
COPY --chown=vscode:vscode mise.toml /home/vscode/.config/mise/config.toml

USER vscode
RUN mise trust /home/vscode/.config/mise/config.toml && mise install

# Shims for non-interactive commands (postCreate, VS Code tasks); activate for interactive shells
ENV PATH="/home/vscode/.local/share/mise/shims:${PATH}"
RUN echo 'eval "$(mise activate bash)"' >> /home/vscode/.bashrc \
    && echo 'eval "$(mise activate zsh)"' >> /home/vscode/.zshrc

USER root
