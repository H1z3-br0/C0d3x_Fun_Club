# Single sandbox image ("one mold") for every CTF solver container.
#
# It ships only the package managers + core toolchain. Anything domain-specific
# (radare2, sagemath, volatility, jadx, frida, torch, …) is installed at runtime
# by the agent via the `ctf-install` helper, so we don't bake 22 profile images.
#
#   docker build -t ctf-swarm:base .

FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_DEFAULT_TIMEOUT=600
ENV PIP_PROGRESS_BAR=off
ENV PIP_ROOT_USER_ACTION=ignore
ENV TERM=xterm-256color
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Shared tool-cache layout consumed by container/ctf-install.
ENV CTF_TASK=/workspace/task
ENV CTF_ARTIFACTS=/workspace/artifacts
ENV CTF_TOOL_CACHE=/workspace/tool-cache
ENV CTF_BIN_DIR=/workspace/tool-cache/bin
ENV CTF_PYTHON_PREFIX=/workspace/tool-cache/python
ENV CTF_CARGO_ROOT=/workspace/tool-cache/.cargo-root
ENV CTF_CARGO_HOME=/workspace/tool-cache/.cargo-home
ENV CTF_GO_BIN=/workspace/tool-cache/bin
ENV CTF_GEM_HOME=/workspace/tool-cache/.gem
ENV CTF_NPM_PREFIX=/workspace/tool-cache/.npm-global
ENV PYTHONPATH=/workspace/tool-cache/python/lib/python3.12/site-packages:/workspace/tool-cache/python/lib64/python3.12/site-packages
ENV PATH=/workspace/tool-cache/bin:/workspace/tool-cache/python/bin:/workspace/tool-cache/.cargo-root/bin:/workspace/tool-cache/.npm-global/bin:/workspace/tool-cache/.gem/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Package managers + core utilities only:
#   - apt (base), pip (python:3.12 base), npm (nodejs), go (golang-go)
#   - build-essential / binutils / gdb so the agent can compile and debug
#   - curl/wget/git/file/unzip/xxd for fetching and inspecting inputs
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      bash binutils build-essential ca-certificates curl file gdb git \
      golang-go less nodejs npm procps unzip wget xxd; \
    rm -rf /var/lib/apt/lists/*

# Tiny CTF core that nearly every challenge needs, kept baked in so each
# container doesn't reinstall it. Everything else: `ctf-install pip <pkg>`.
RUN set -eux; \
    python -m pip install --no-cache-dir --break-system-packages \
      --prefer-binary --retries 10 --timeout 600 \
      pwntools pycryptodome python-magic

# Runtime tool installer + cheatsheet (apt/pip/gem/cargo/go/npm into tool-cache).
COPY container/ctf-install /usr/local/bin/ctf-install
COPY container/ctf-tools /usr/local/bin/ctf-tools
RUN chmod +x /usr/local/bin/ctf-install /usr/local/bin/ctf-tools

WORKDIR /workspace/task
CMD ["sleep", "infinity"]
