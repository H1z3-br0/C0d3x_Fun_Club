# CTF Agent

Autonomous CTF (Capture The Flag) solver that races multiple AI models against
challenges in parallel. All LLM traffic is routed through a local
[CLIProxyAPI](https://github.com/router-for-me/cli-proxy-api) instance, which
fans out to Codex / Claude / Gemini via OAuth-backed accounts.

## How It Works

A **coordinator** LLM manages the competition while **solver swarms** attack
individual challenges. Each swarm runs multiple models simultaneously — the
first to find the flag wins.

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

Each challenge runs in its own Docker container, spawned from a single base
image; the agent installs whatever domain tools it needs at runtime. All
solver agents racing on that challenge share the one container and its
`/challenge/workspace`. Solvers never give up — they keep trying different
approaches until the flag is found or the coordinator kills the swarm.

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
# 1. Start cli-proxy-api (port 8317 by default)
/home/dima/cliproxyapi/cli-proxy-api --config /home/dima/cliproxyapi/config.yaml

# 2. Install this project
uv sync

# 3. Build the single sandbox image
./build_profiles.sh  # builds ctf-swarm:base (the one image used for every task)

# 4. Configure
cp .env.example .env
# Edit .env — set OPENAI_API_KEY to one of the keys from cliproxyapi/config.yaml
#             set CTFD_URL / CTFD_TOKEN

# 5. Run against a CTFd instance
uv run ctf-solve run \
  --ctfd-url https://ctf.example.com \
  --ctfd-token ctfd_your_token \
  --challenges-dir challenges \
  --max-challenges 10 \
  -v
```

## Solver Models

The `DEFAULT_MODELS` list in [backend/models.py](backend/models.py) specifies
which model aliases to spawn per challenge:

| Spec | Notes |
|------|-------|
| `codex/gpt-5.4` | Best overall solver |
| `codex/gpt-5.4-mini` | Fast, good for easy challenges |
| `codex/gpt-5.3-codex` | Reasoning-heavy |

These names must match aliases exposed by your `cliproxyapi/config.yaml`. The
`codex/` prefix is informational — the proxy routes by model alias. Override
with `--models codex/gpt-5.4 codex/gpt-5.4-mini`.

## Sandbox

There is **one image for every challenge** — `ctf-swarm:base` (override with
`--image`). It ships only the package managers and core toolchain (python/pip,
node/npm, go, apt, build-essential, gdb, binutils, git, curl) plus a tiny CTF
core (pwntools, pycryptodome, python-magic). Anything domain-specific
(radare2, sagemath, volatility, jadx, …) the agent **installs at runtime**
inside its container.

Each challenge gets its own container (labelled `ctf-challenge=<name>`), and
all solver agents racing on that challenge share it and its
`/challenge/workspace`. Containers are created per task from the one image and
destroyed when the task finishes — only the image is built ahead of time.

## Operator Messaging

While the coordinator is running, you can push hints to it:

```bash
uv run ctf-solve msg "try RSA Wiener on crypto-3"
```

The coordinator writes its chosen port to `findings/.coordinator-port` on
startup, so `msg` discovers it automatically. Override with `--port` if needed.

## Features

- Multi-model racing on every challenge
- Auto-spawn for newly appearing challenges, auto-kill on confirmed solve
- Coordinator LLM reads per-solver traces and crafts targeted bumps
- Cross-solver insights shared through a message bus with per-model cursors
- One Docker sandbox per challenge, shared by its solver agents (tools installed at runtime)
- Deduplicated flag submission with per-submitter escalating cooldown
- Graceful proxy health-check on startup (fail fast if cli-proxy-api is down)
- Persistent memory of past solves via LanceDB (hash-bag-of-words embedding)

## Configuration cheatsheet

`.env`:

```env
CTFD_URL=https://ctf.example.com
CTFD_TOKEN=ctfd_your_token
OPENAI_BASE_URL=http://127.0.0.1:8317/v1
OPENAI_API_KEY=sk-from-cliproxyapi-config-yaml
```

`cliproxyapi/config.yaml` must expose the model aliases used in
`DEFAULT_MODELS` (through `codex-api-key`, `openai-compatibility`, or OAuth
accounts in `~/.cli-proxy-api/*.json`).

## Acknowledgements

- [es3n1n/Eruditus](https://github.com/es3n1n/Eruditus) — CTFd interaction and
  HTML helpers in `pull_challenges.py`
- [router-for-me/cli-proxy-api](https://github.com/router-for-me/cli-proxy-api)
  — local OpenAI-compatible proxy that fans out to OAuth-backed upstreams
