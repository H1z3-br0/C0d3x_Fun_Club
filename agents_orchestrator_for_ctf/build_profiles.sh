#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
PROJECT_ROOT="${SCRIPT_DIR}"
PROFILES_DOC="${PROJECT_ROOT}/container/profiles.md"
DOCKERFILE="${PROJECT_ROOT}/Dockerfile"

read_profiles() {
  awk '
    /<!-- profiles:start -->/ { in_block=1; next }
    /<!-- profiles:end -->/ { in_block=0 }
    in_block && $0 ~ /^- `/ {
      match($0, /`[a-z0-9-]+`/)
      if (RSTART > 0) {
        print substr($0, RSTART + 1, RLENGTH - 2)
      }
    }
  ' "${PROFILES_DOC}"
}

mapfile -t all_profiles < <(read_profiles)

if [ "${#all_profiles[@]}" -eq 0 ]; then
  echo "Не удалось загрузить профили из ${PROFILES_DOC}" >&2
  exit 1
fi

if [ "$#" -gt 0 ]; then
  selected_profiles=("$@")
else
  selected_profiles=("${all_profiles[@]}")
fi

for profile in "${selected_profiles[@]}"; do
  valid=0
  for known in "${all_profiles[@]}"; do
    if [ "${profile}" = "${known}" ]; then
      valid=1
      break
    fi
  done
  if [ "${valid}" -ne 1 ]; then
    echo "Неизвестный профиль: ${profile}" >&2
    echo "Доступные профили: ${all_profiles[*]}" >&2
    exit 1
  fi
done

echo "=== Building ctf-swarm:base ==="
docker build \
  --target base \
  --build-arg "PROFILE=base" \
  -t "ctf-swarm:base" \
  -f "${DOCKERFILE}" \
  "${PROJECT_ROOT}"

for profile in "${selected_profiles[@]}"; do
  if [ "${profile}" = "base" ]; then
    continue
  fi
  echo "=== Building ctf-swarm:${profile} ==="
  docker build \
    --target "${profile}" \
    --build-arg "PROFILE=${profile}" \
    --build-arg "PROFILE_BASE_IMAGE=ctf-swarm:base" \
    -t "ctf-swarm:${profile}" \
    -f "${DOCKERFILE}" \
    "${PROJECT_ROOT}"
done
