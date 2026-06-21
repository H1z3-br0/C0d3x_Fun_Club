# Single CTF sandbox image: ctf-swarm:base
#
# Philosophy: bake in a small, fast core. Everything heavy (radare2, angr, z3,
# volatility, sqlmap, ...) is installed on demand from inside the container via
# `ctf-install`, into a writable tool-cache. One image, quick to build and maintain.

FROM python:3.12-slim-bookworm

ENV DEBIAN_FRONTEND=noninteractive
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PIP_DEFAULT_TIMEOUT=600
ENV PIP_PROGRESS_BAR=off
ENV PIP_ROOT_USER_ACTION=ignore
ENV TERM=xterm-256color
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Writable tool-cache used by `ctf-install` for on-demand tools. Lives UNDER
# /challenge/workspace (the host-bind-mounted dir) so installs survive a container
# restart instead of being lost with the ephemeral rootfs.
ENV CTF_TOOL_CACHE=/challenge/workspace/.tool-cache
ENV CTF_ARTIFACTS=/challenge/workspace/.tool-cache/artifacts
ENV CTF_BIN_DIR=/challenge/workspace/.tool-cache/bin
ENV CTF_PYTHON_PREFIX=/challenge/workspace/.tool-cache/python
ENV CTF_CARGO_ROOT=/challenge/workspace/.tool-cache/.cargo-root
ENV CTF_CARGO_HOME=/challenge/workspace/.tool-cache/.cargo-home
ENV CTF_GO_BIN=/challenge/workspace/.tool-cache/bin
ENV CTF_GEM_HOME=/challenge/workspace/.tool-cache/.gem
ENV CTF_NPM_PREFIX=/challenge/workspace/.tool-cache/.npm-global
ENV PYTHONPATH=/challenge/workspace/.tool-cache/python/lib/python3.12/site-packages:/challenge/workspace/.tool-cache/python/lib64/python3.12/site-packages
ENV PATH=/challenge/workspace/.tool-cache/bin:/challenge/workspace/.tool-cache/python/bin:/challenge/workspace/.tool-cache/.cargo-root/bin:/challenge/workspace/.tool-cache/.npm-global/bin:/challenge/workspace/.tool-cache/.gem/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin

SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# Baked-in core toolchain. gcc/g++/make come from build-essential; objdump/strings/nm
# from binutils. Anything else: `ctf-install apt|pip|...` at runtime.
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      bash binutils build-essential ca-certificates curl file gdb git \
      golang-go less nodejs npm netcat-openbsd procps socat strace unzip wget xxd; \
    rm -rf /var/lib/apt/lists/*

# Base Python libs that virtually every challenge needs.
RUN set -eux; \
    python -m pip install --no-cache-dir --break-system-packages \
      --prefer-binary --retries 10 --timeout 600 \
      pwntools pycryptodome python-magic

COPY container/ctf-install /usr/local/bin/ctf-install
COPY container/ctf-tools /usr/local/bin/ctf-tools
RUN chmod +x /usr/local/bin/ctf-install /usr/local/bin/ctf-tools

WORKDIR /challenge/workspace
CMD ["sleep", "infinity"]
