#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
BINARY="${SCRIPT_DIR}/cli-proxy-api"
RUN_DIR="${SCRIPT_DIR}/run"

if [ ! -x "${BINARY}" ]; then
  echo "Не найден исполняемый бинарник: ${BINARY}" >&2
  echo "Положите cli-proxy-api в deploy/ и выполните chmod +x deploy/cli-proxy-api" >&2
  exit 1
fi

mkdir -p "${RUN_DIR}"

instances=(
  "master-claude|8311|orchestrator-master-claude-key|${SCRIPT_DIR}/cliproxy/master-claude/config.yaml"
  "support-claude|8312|orchestrator-support-claude-key|${SCRIPT_DIR}/cliproxy/support-claude/config.yaml"
  "reserve-codex|8313|orchestrator-reserve-codex-key|${SCRIPT_DIR}/cliproxy/reserve-codex/config.yaml"
  "executors-codex|8314|orchestrator-executors-codex-key|${SCRIPT_DIR}/cliproxy/executors-codex/config.yaml"
)

wait_for_models() {
  local name="$1"
  local port="$2"
  local api_key="$3"
  local attempts=30
  local url="http://127.0.0.1:${port}/v1/models"
  local output

  for _ in $(seq 1 "${attempts}"); do
    if output="$(curl -fsS -H "Authorization: Bearer ${api_key}" "${url}")"; then
      if printf '%s' "${output}" | grep -q '"data"'; then
        echo "OK: ${name} отвечает на ${url}"
        return 0
      fi
    fi
    sleep 1
  done

  echo "Инстанс ${name} не начал отвечать на /v1/models" >&2
  return 1
}

start_instance() {
  local name="$1"
  local port="$2"
  local api_key="$3"
  local config="$4"
  local auth_dir="${SCRIPT_DIR}/cliproxy/${name}/auth"
  local log_dir="${SCRIPT_DIR}/cliproxy/${name}/logs"
  local pid_file="${RUN_DIR}/${name}.pid"
  local log_file="${log_dir}/server.log"

  mkdir -p "${auth_dir}" "${log_dir}"

  if [ -f "${pid_file}" ]; then
    local old_pid
    old_pid="$(cat "${pid_file}")"
    if kill -0 "${old_pid}" >/dev/null 2>&1; then
      echo "Уже запущен: ${name} (pid=${old_pid})"
      wait_for_models "${name}" "${port}" "${api_key}"
      return 0
    fi
    rm -f "${pid_file}"
  fi

  echo "Стартую ${name} на порту ${port}"
  (
    cd "${REPO_ROOT}"
    nohup "${BINARY}" --config "${config}" >>"${log_file}" 2>&1 &
    echo $! > "${pid_file}"
  )

  wait_for_models "${name}" "${port}" "${api_key}" || {
    echo "Последние строки лога ${name}:" >&2
    tail -n 50 "${log_file}" >&2 || true
    exit 1
  }
}

for entry in "${instances[@]}"; do
  IFS='|' read -r name port api_key config <<< "${entry}"
  start_instance "${name}" "${port}" "${api_key}" "${config}"
done

echo
echo "Все 4 инстанса CLIProxyAPI запущены."
echo "PID-файлы: ${RUN_DIR}"
