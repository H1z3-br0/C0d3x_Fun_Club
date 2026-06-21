# CTF Agent

Autonomous CTF (Capture The Flag) solver that races GPT-5.5 and Claude Opus
against challenges in parallel. All LLM traffic is routed through a local
[CLIProxyAPI](https://github.com/router-for-me/cli-proxy-api) instance, which
fans out to Codex / Claude / Gemini via OAuth-backed accounts.

## How It Works

A **coordinator** LLM manages the competition while **solver swarms** attack
individual challenges. By default each swarm races three models — `gpt-5.5`,
`claude-opus-4-8`, and `claude-opus-4-7` — and the first to confirm a flag wins.
The coordinator runs on GPT-5.5.

```
                        +-----------------+
                        |  CTFd Platform  |
                        +--------+--------+
                                 |
                        +--------v--------+
                        |  Poller (5s)    |
                        +--------+--------+
                                 |
                        +--------v--------+
                        | Coordinator LLM |
                        +--------+--------+
                                 |
              +------------------+------------------+
              |                  |                  |
     +--------v--------+ +------v---------+ +------v---------+
     | Swarm:          | | Swarm:         | | Swarm:         |
     | challenge-1     | | challenge-2    | | challenge-N    |
     +--------+--------+ +--------+-------+ +--------+-------+
              |                   |                  |
              +-------------------+------------------+
                                  |
                          +-------v-------+
                          |  CLIProxyAPI  |
                          |  :8317 /v1    |
                          +-------+-------+
                                  |
               +------------------+------------------+
               |                  |                  |
         +-----v-----+      +-----v-----+      +-----v-----+
         |  Codex    |      |  Claude   |      |  Gemini   |
         |  OAuth    |      |  OAuth    |      |  OAuth    |
         +-----------+      +-----------+      +-----------+
```

Each challenge gets one Docker container (`ctf-swarm:base`) shared by all solver
models in its swarm. Solvers are persistent — when stuck they get "bumped" with
sibling insights and a fresh step budget and keep trying different approaches,
until the flag is found, the coordinator kills the swarm, or a solver hits its
safety limits (repeated hard errors or a context-window rotation cap).

## Prerequisites

- Python 3.12+
- Docker
- A running [cli-proxy-api](https://github.com/router-for-me/cli-proxy-api)
  instance with at least one upstream OAuth account configured (Codex / Claude /
  Gemini). Default port expected: **8317**.

The agent does **not** call upstream LLM APIs directly. It always goes through
`cli-proxy-api`'s OpenAI-compatible `/v1/chat/completions` endpoint.

## Quick Start

```bash
# 1. Start cli-proxy-api (port 8317 by default). Copy the sample config and add
#    your own api-key + OAuth accounts — config.yaml is gitignored.
cp config.example.yaml config.yaml
cli-proxy-api --config config.yaml

# 2. Install this project
uv sync

# 3. Build the sandbox image (single image — ctf-swarm:base)
./build_sandbox.sh

# 4. Configure
cp .env.example .env
# Edit .env — set CLIPROXY_API_KEY to one of the keys from cliproxyapi/config.yaml
#             set CTFD_URL / CTFD_TOKEN

# 5. Run against a CTFd instance
uv run ctf-solve run \
  --ctfd-url https://ctf.example.com \
  --ctfd-token ctfd_your_token \
  --challenges-dir challenges \
  --max-challenges 10 \
  -v
```

> **Dry run (`--no-submit`):** flags are recorded but **not** submitted to CTFd.
> A found flag is treated as "confirmed" only to stop the swarm — it does **not**
> mean CTFd accepted it. Re-run without `--no-submit` for real verification.

## Solver Models

The `DEFAULT_MODELS` list in [backend/models.py](backend/models.py) is the
default solver hive — every challenge is raced by all three:

| Spec | Model id | Notes |
|------|----------|-------|
| `codex/gpt-5.5` | `gpt-5.5` | Routed via Codex OAuth |
| `claude/claude-opus-4-8` | `claude-opus-4-8` | Routed via Claude OAuth |
| `claude/claude-opus-4-7` | `claude-opus-4-7` | Routed via Claude OAuth |

Each model id must be exposed as an alias by your `cliproxyapi/config.yaml`
(Codex account for GPT-5.5, Claude account for the Opus models). The
`provider/` prefix (`codex/`, `claude/`) is informational — the proxy routes by
model alias. Pass `--models codex/gpt-5.5` to run a single model, or any subset.
Any id outside the allow-list fails at startup. The coordinator defaults to
`codex/gpt-5.5` (override with `--coordinator-model`).

## Sandbox

The project uses a **single** Docker image, `ctf-swarm:base`, built from the
root [Dockerfile](Dockerfile) via `./build_sandbox.sh`.

- **Each challenge gets exactly one container**, shared by all solver models in
  the swarm. Challenge files are copied into `/challenge/workspace` (read-write);
  read-only originals stay at `/challenge/distfiles`.
- **Baked in:** `python3`/`pip`, `node`/`npm`, `go`, `gcc`/`g++`, `gdb`, `git`,
  `curl`, `file`, `xxd`, plus Python `pwntools`, `pycryptodome`, `python-magic`.
- **Everything heavier installs on demand** from inside the container via
  `ctf-install` (e.g. `ctf-install apt radare2 binwalk`,
  `ctf-install pip angr z3-solver`) — no need to build or maintain many images.

Override the image with `--image <name>` if you really need a different one.

## Operator Messaging

While the coordinator is running, you can push hints to it:

```bash
uv run ctf-solve msg "try RSA Wiener on crypto-3"
```

The coordinator writes its chosen port to `findings/.coordinator-port` on
startup, so `msg` discovers it automatically. Override with `--port` if needed.

## Features

- Multi-model hive (GPT-5.5 + Claude Opus 4.8/4.7) racing every challenge
- Auto-spawn for newly appearing challenges, auto-kill on confirmed solve
- Coordinator LLM reads per-solver traces and crafts targeted bumps
- Cross-solver insights shared through a message bus with per-model cursors
- One shared Docker sandbox per challenge (single `ctf-swarm:base` image)
- Deduplicated flag submission with per-submitter escalating cooldown
- Graceful proxy health-check on startup (fail fast if cli-proxy-api is down)
- Persistent memory of past solves via LanceDB (hash-bag-of-words keyword
  similarity — token overlap, not a semantic embedding)

## Configuration cheatsheet

`.env`:

```env
CTFD_URL=https://ctf.example.com
CTFD_TOKEN=ctfd_your_token
OPENAI_BASE_URL=http://127.0.0.1:8317/v1
CLIPROXY_API_KEY=sk-from-cliproxyapi-config-yaml  # OPENAI_API_KEY still accepted as a legacy alias
```

`cliproxyapi/config.yaml` must expose every model id in `DEFAULT_MODELS`
(`gpt-5.5`, `claude-opus-4-8`, `claude-opus-4-7`) as an alias — through
`codex-api-key`, `openai-compatibility`, or OAuth accounts in
`~/.cli-proxy-api/*.json`.

## Acknowledgements

- [es3n1n/Eruditus](https://github.com/es3n1n/Eruditus) — CTFd interaction and
  HTML helpers in `pull_challenges.py`
- [router-for-me/cli-proxy-api](https://github.com/router-for-me/cli-proxy-api)
  — local OpenAI-compatible proxy that fans out to OAuth-backed upstreams
