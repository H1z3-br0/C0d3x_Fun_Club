# CLIProxyAPI Deployment For 4 Pools

Этот каталог готовит 4 отдельных инстанса CLIProxyAPI для оркестратора:

- `master-claude` -> CC1
- `support-claude` -> CC2
- `reserve-codex` -> S1-S4
- `executors-codex` -> Codex workers

Важно: реальные аккаунты привязываются не через email в `config.yaml` оркестратора, а через OAuth логин в нужный инстанс CLIProxyAPI. Email-поля в корневом [config.yaml](/Users/macbook/agents_orchestrator_for_ctf/config.yaml) используются как человекочитаемые метки в логах и ролях.

## Что уже создано

- `deploy/cliproxy/master-claude/config.yaml`
- `deploy/cliproxy/support-claude/config.yaml`
- `deploy/cliproxy/reserve-codex/config.yaml`
- `deploy/cliproxy/executors-codex/config.yaml`
- `deploy/start_cliproxy.sh`
- `deploy/login_accounts.sh`
- обновлённый корневой `config.yaml` оркестратора

## Перед началом

1. Убедитесь, что бинарник CLIProxyAPI лежит в:

```bash
deploy/cli-proxy-api
```

2. Сделайте его исполняемым:

```bash
chmod +x deploy/cli-proxy-api
chmod +x deploy/start_cliproxy.sh
chmod +x deploy/login_accounts.sh
```

3. Откройте корневой `config.yaml` и замените только email-плейсхолдеры:

- `REPLACE_WITH_CC1_EMAIL`
- `REPLACE_WITH_CC2_EMAIL`
- `REPLACE_WITH_RESERVE01_EMAIL` ... `REPLACE_WITH_RESERVE04_EMAIL`
- `REPLACE_WITH_WORKER01_EMAIL` ... `REPLACE_WITH_WORKER20_EMAIL`

## Как залогинить аккаунты

CLIProxyAPI по официальной документации использует:

- `--claude-login` для Claude OAuth
- `--codex-login` для Codex OAuth

Если сервер без браузера, используйте:

```bash
NO_BROWSER=1 ./deploy/login_accounts.sh master-claude
```

CLIProxyAPI выведет URL для логина вместо автозапуска браузера.

### 1. CC1 / основной Claude аккаунт

```bash
./deploy/login_accounts.sh master-claude
```

Что делать:

- в браузере войти под аккаунтом Claude для CC1
- после успешного OAuth токен сохранится в `deploy/cliproxy/master-claude/auth`

### 2. CC2 / support Claude аккаунт

```bash
./deploy/login_accounts.sh support-claude
```

Что делать:

- в браузере войти под отдельным Claude аккаунтом для CC2
- токен сохранится в `deploy/cliproxy/support-claude/auth`

### 3. Резервные Codex аккаунты

```bash
./deploy/login_accounts.sh reserve-codex
```

Что делать:

- повторить эту команду до 4 раз
- каждый раз входить под новым Codex аккаунтом
- все эти аккаунты попадут в пул `reserve-codex`

### 4. Executor Codex аккаунты

```bash
./deploy/login_accounts.sh executors-codex
```

Что делать:

- повторить эту команду до 20 раз
- каждый раз входить под новым Codex аккаунтом
- все эти аккаунты попадут в пул `executors-codex`

## Как запустить инстансы

Один скрипт запускает все 4 инстанса, пишет PID-файлы и проверяет `/v1/models`:

```bash
./deploy/start_cliproxy.sh
```

Что делает скрипт:

- стартует `master-claude` на `127.0.0.1:8311`
- стартует `support-claude` на `127.0.0.1:8312`
- стартует `reserve-codex` на `127.0.0.1:8313`
- стартует `executors-codex` на `127.0.0.1:8314`
- создаёт `auth/`, `logs/` и `run/`
- проверяет, что каждый инстанс отвечает на `/v1/models`

Логи лежат в:

- `deploy/cliproxy/master-claude/logs/server.log`
- `deploy/cliproxy/support-claude/logs/server.log`
- `deploy/cliproxy/reserve-codex/logs/server.log`
- `deploy/cliproxy/executors-codex/logs/server.log`

PID-файлы лежат в:

```bash
deploy/run/
```

## Как проверить, что всё работает

### 1. Проверка списка моделей

```bash
curl -H 'Authorization: Bearer orchestrator-master-claude-key' \
  http://127.0.0.1:8311/v1/models

curl -H 'Authorization: Bearer orchestrator-support-claude-key' \
  http://127.0.0.1:8312/v1/models

curl -H 'Authorization: Bearer orchestrator-reserve-codex-key' \
  http://127.0.0.1:8313/v1/models

curl -H 'Authorization: Bearer orchestrator-executors-codex-key' \
  http://127.0.0.1:8314/v1/models
```

Ожидается JSON с полем `data`.

### 2. Проверка, что имена моделей подходят оркестратору

По умолчанию конфиги рассчитаны на:

- Claude -> `claude-code`
- Codex -> `codex`

Это делается через `oauth-model-alias` в конфиге CLIProxyAPI.

Если в `/v1/models` вы не видите `claude-code` или `codex`, значит фактическое upstream имя у провайдера отличается от ожидаемого. Тогда:

1. откройте соответствующий файл `deploy/cliproxy/.../config.yaml`
2. измените поле `oauth-model-alias.*.name`
3. перезапустите инстанс

Корневой `config.yaml` оркестратора при этом можно оставить без изменений.

## Как запустить оркестратор

После успешного логина аккаунтов и старта всех 4 инстансов:

```bash
python main.py --task-dir ./one_task --flag-format "CTF{...}"
```

Для MULTI режима:

```bash
python main.py \
  --mode multi \
  --ctfd-url https://ctf.example.com \
  --ctfd-token YOUR_CTFD_TOKEN \
  --flag-format "CTF{...}"
```

## Практический порядок запуска

1. `chmod +x deploy/cli-proxy-api deploy/start_cliproxy.sh deploy/login_accounts.sh`
2. заменить email-плейсхолдеры в корневом `config.yaml`
3. залогинить `master-claude`
4. залогинить `support-claude`
5. залогинить `reserve-codex` нужное число раз
6. залогинить `executors-codex` нужное число раз
7. запустить `./deploy/start_cliproxy.sh`
8. проверить `curl ... /v1/models` на всех 4 портах
9. запустить оркестратор
