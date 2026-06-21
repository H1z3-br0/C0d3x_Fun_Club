#!/usr/bin/env bash
# Build the single CTF sandbox image (ctf-swarm:base) from the root Dockerfile.
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"

echo "=== Building ctf-swarm:base ==="
docker build -t "ctf-swarm:base" -f "${SCRIPT_DIR}/Dockerfile" "${SCRIPT_DIR}"
echo "Done. One image for every challenge; extra tools install on demand via ctf-install."
