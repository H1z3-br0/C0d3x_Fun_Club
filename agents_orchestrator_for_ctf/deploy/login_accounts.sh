#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
REPO_ROOT="$(CDPATH= cd -- "${SCRIPT_DIR}/.." && pwd)"
BINARY="${SCRIPT_DIR}/cli-proxy-api"
NO_BROWSER_FLAG=()

if [ ! -x "${BINARY}" ]; then
  echo "Не найден исполняемый бинарник: ${BINARY}" >&2
  echo "Положите cli-proxy-api в deploy/ и выполните chmod +x deploy/cli-proxy-api" >&2
  exit 1
fi

if [ "${NO_BROWSER:-0}" = "1" ]; then
  NO_BROWSER_FLAG+=(--no-browser)
fi

run_login() {
  local config="$1"
  local login_flag="$2"
  (
    cd "${REPO_ROOT}"
    "${BINARY}" --config "${config}" "${login_flag}" "${NO_BROWSER_FLAG[@]}"
  )
}

print_help() {
  cat <<'EOF'
Использование:
  ./deploy/login_accounts.sh master-claude
  ./deploy/login_accounts.sh support-claude
  ./deploy/login_accounts.sh reserve-codex
  ./deploy/login_accounts.sh executors-codex

Опционально:
  NO_BROWSER=1 ./deploy/login_accounts.sh master-claude

Что делать:
  1. Запускайте группу по одной.
  2. Повторяйте одну и ту же команду столько раз, сколько аккаунтов хотите добавить в этот пул.
  3. Каждый повтор логиньте под другим реальным аккаунтом в браузере.

Группы аккаунтов:

  master-claude
    Использовать только для CC1.
    Повторить 1 раз, если у вас один основной Claude аккаунт.

  support-claude
    Использовать только для CC2.
    Повторить 1 раз, если у вас один отдельный Claude аккаунт для поддержки.

  reserve-codex
    Использовать для 1-4 резервных Codex аккаунтов.
    Повторить команду 4 раза, если хотите полный резервный пул.

  executors-codex
    Использовать для пула Codex воркеров.
    Повторить команду 20 раз, если хотите полный executor pool.

Команды по инстансам:

  # CC1 / master Claude pool
  ./deploy/login_accounts.sh master-claude

  # CC2 / support Claude pool
  ./deploy/login_accounts.sh support-claude

  # S1-S4 / reserve Codex pool
  ./deploy/login_accounts.sh reserve-codex

  # Executors / worker Codex pool
  ./deploy/login_accounts.sh executors-codex
EOF
}

case "${1:-help}" in
  master-claude)
    echo "Логин в пул master-claude."
    echo "В браузере войдите под аккаунтом CC1."
    run_login "${SCRIPT_DIR}/cliproxy/master-claude/config.yaml" --claude-login
    ;;
  support-claude)
    echo "Логин в пул support-claude."
    echo "В браузере войдите под аккаунтом CC2."
    run_login "${SCRIPT_DIR}/cliproxy/support-claude/config.yaml" --claude-login
    ;;
  reserve-codex)
    echo "Логин в пул reserve-codex."
    echo "Повторите эту команду для reserve1..reserve4, каждый раз под новым аккаунтом Codex."
    run_login "${SCRIPT_DIR}/cliproxy/reserve-codex/config.yaml" --codex-login
    ;;
  executors-codex)
    echo "Логин в пул executors-codex."
    echo "Повторите эту команду для worker01..worker20, каждый раз под новым аккаунтом Codex."
    run_login "${SCRIPT_DIR}/cliproxy/executors-codex/config.yaml" --codex-login
    ;;
  help|-h|--help|"")
    print_help
    ;;
  *)
    echo "Неизвестная группа: ${1}" >&2
    echo >&2
    print_help >&2
    exit 1
    ;;
esac
