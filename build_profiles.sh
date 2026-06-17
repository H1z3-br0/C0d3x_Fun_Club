#!/usr/bin/env bash
# Build the single sandbox image used for every solver container.
# Domain tools are installed at runtime by the agent via `ctf-install`.
#
# Usage: ./build_profiles.sh [tag]   (default tag: ctf-swarm:base)
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
TAG="${1:-ctf-swarm:base}"

echo "=== Building ${TAG} ==="
docker build -t "${TAG}" -f "${SCRIPT_DIR}/Dockerfile" "${SCRIPT_DIR}"
