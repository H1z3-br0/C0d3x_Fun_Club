"""Per-tool-call JSONL event tracing — one file per solver, streamable via tail -f."""

from __future__ import annotations

import atexit
import json
import time
from pathlib import Path


def _sanitize(s: str) -> str:
    return s.replace("/", "_").replace(" ", "_")


def summarize_trace(path: str, last_n: int = 40) -> list[str]:
    """Render the last `last_n` JSONL trace events as short human-readable lines.

    Shared by the swarm's rotation summaries and the coordinator's read_solver_trace.
    """
    try:
        lines = Path(path).read_text().strip().split("\n")
    except FileNotFoundError:
        return ["Trace file not found."]
    except Exception as e:
        return [f"Trace read error: {e}"]

    summary: list[str] = []
    for line in lines[-last_n:] if lines else []:
        try:
            d = json.loads(line)
        except Exception:
            summary.append(line[:120])
            continue
        t = d.get("type", "?")
        step = d.get("step", "?")
        if t == "tool_call":
            summary.append(f"step {step} CALL {d.get('tool', '?')}: {str(d.get('args', ''))[:120]}")
        elif t == "tool_result":
            summary.append(f"step {step} RESULT {d.get('tool', '?')}: {str(d.get('result', ''))[:120]}")
        elif t == "model_response":
            summary.append(f"step {step} MODEL: {str(d.get('text', ''))[:160]}")
        elif t in ("finish", "error", "bump", "turn_failed"):
            summary.append(f"** {t}: {json.dumps({k: v for k, v in d.items() if k != 'ts'})}")
        elif t == "usage":
            summary.append(
                f"usage: in={d.get('input_tokens', 0)} out={d.get('output_tokens', 0)} "
                f"cost=${d.get('cost_usd', 0):.4f}"
            )
        else:
            summary.append(f"{t}: {str(d)[:120]}")
    return summary


class SolverTracer:
    """Append-only JSONL event tracer. Flushes every write for tail -f streaming."""

    def __init__(self, challenge_name: str, model_id: str, log_dir: str = "logs") -> None:
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        ts = time.strftime("%Y%m%d-%H%M%S")
        self.path = str(Path(log_dir) / f"trace-{_sanitize(challenge_name)}-{_sanitize(model_id)}-{ts}.jsonl")
        self._fh = open(self.path, "a")
        atexit.register(self._close)

    def close(self) -> None:
        """Explicitly close the trace file. Safe to call multiple times."""
        if not self._fh.closed:
            try:
                self._fh.close()
            except Exception:
                pass

    _close = close  # atexit compat

    def _write(self, event: dict) -> None:
        try:
            self._fh.write(json.dumps({"ts": time.time(), **event}) + "\n")
            self._fh.flush()
        except Exception:
            pass

    def tool_call(self, tool_name: str, args: dict | str, step: int) -> None:
        args_str = args if isinstance(args, str) else json.dumps(args)
        self._write({"type": "tool_call", "tool": tool_name, "args": args_str[:2000], "step": step})

    def tool_result(self, tool_name: str, result: str, step: int) -> None:
        self._write({"type": "tool_result", "tool": tool_name, "result": result[:2000], "step": step})

    def model_response(self, text: str, step: int, input_tokens: int = 0, output_tokens: int = 0) -> None:
        self._write({"type": "model_response", "text": text[:1000], "step": step,
                      "input_tokens": input_tokens, "output_tokens": output_tokens})

    def usage(self, input_tokens: int, output_tokens: int, cache_read: int, cost_usd: float) -> None:
        self._write({"type": "usage", "input_tokens": input_tokens, "output_tokens": output_tokens,
                      "cache_read_tokens": cache_read, "cost_usd": round(cost_usd, 6)})

    def event(self, kind: str, **kwargs) -> None:
        self._write({"type": kind, **kwargs})
