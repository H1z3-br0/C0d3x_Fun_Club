from __future__ import annotations

import json
import os
import posixpath
import re
import textwrap
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any

import yaml


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def ensure_dir(path: str | Path) -> Path:
    resolved = Path(path)
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def slugify(value: str) -> str:
    collapsed = re.sub(r"[^a-zA-Z0-9]+", "-", value.strip().lower())
    return collapsed.strip("-") or "task"


def json_dumps(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)


def load_yaml_file(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"{path} должен содержать YAML-словарь")
    return payload


def dump_yaml_file(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )


def flag_format_to_regex(flag_format: str) -> str:
    escaped = re.escape(flag_format)
    return escaped.replace(r"\.\.\.", r"[^}]+")


def read_text_file(path: Path, limit: int = 20_000) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def summarize_directory(task_dir: Path, max_files: int = 100) -> str:
    lines: list[str] = []
    files = sorted(item for item in task_dir.rglob("*") if item.is_file())
    for file_path in files[:max_files]:
        rel = file_path.relative_to(task_dir)
        size = file_path.stat().st_size
        lines.append(f"- {rel} ({size} bytes)")
    if len(files) > max_files:
        lines.append(f"- ... and {len(files) - max_files} more files")
    return "\n".join(lines)


def collect_text_snippets(
    task_dir: Path, max_files: int = 10, max_chars_per_file: int = 4_000
) -> str:
    snippets: list[str] = []
    candidates = sorted(item for item in task_dir.rglob("*") if item.is_file())
    for path in candidates:
        if len(snippets) >= max_files:
            break
        suffix = path.suffix.lower()
        if suffix in {
            ".txt",
            ".md",
            ".py",
            ".c",
            ".cpp",
            ".h",
            ".hpp",
            ".js",
            ".ts",
            ".go",
            ".rs",
            ".java",
            ".php",
            ".html",
            ".xml",
            ".json",
            ".yaml",
            ".yml",
            ".sh",
        }:
            body = read_text_file(path, limit=max_chars_per_file)
            if body.strip():
                rel = path.relative_to(task_dir)
                snippets.append(f"## {rel}\n{body}")
    return "\n\n".join(snippets)


def extract_json_object(raw_text: str) -> dict[str, Any]:
    raw_text = raw_text.strip()
    if not raw_text:
        raise ValueError("Пустой ответ модели")

    fenced = re.findall(r"```(?:json)?\s*(\{.*?\})\s*```", raw_text, flags=re.DOTALL)
    candidates = fenced + _balanced_json_candidates(raw_text)

    for candidate in candidates:
        try:
            payload = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            return payload
    raise ValueError("Не удалось извлечь валидный JSON из ответа модели")


def _balanced_json_candidates(text: str) -> list[str]:
    candidates: list[str] = []
    start_positions = [index for index, char in enumerate(text) if char == "{"]
    for start in start_positions:
        candidate = _scan_balanced_json_object(text, start)
        if candidate is not None:
            candidates.append(candidate)
    return candidates


def trim_block(text: str, limit: int = 8_000) -> str:
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[: limit - 200]
    return f"{head}\n\n...[truncated {len(text) - len(head)} chars]"


def relative_workdir(workdir: str) -> str:
    normalized = os.path.normpath(workdir)
    if normalized.startswith(".."):
        raise ValueError("workdir выходит за пределы разрешённых директорий")
    return normalized


def normalize_workspace_workdir(workdir: str) -> str:
    raw = workdir.strip() or "/workspace/task"
    normalized = posixpath.normpath(raw)
    path = PurePosixPath(normalized)
    if path.is_absolute():
        if len(path.parts) < 3 or path.parts[1] != "workspace":
            raise ValueError("Разрешены только пути внутри /workspace")
        root = path.parts[2]
        if root not in {"task", "artifacts"}:
            raise ValueError("Разрешены только /workspace/task и /workspace/artifacts")
        return path.as_posix()

    if normalized in {".", ""}:
        return "/workspace/task"
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError("workdir выходит за пределы разрешённых директорий")
    root = PurePosixPath(normalized).parts[0]
    if root not in {"task", "artifacts"}:
        raise ValueError("Относительный workdir должен начинаться с task/ или artifacts/")
    return f"/workspace/{normalized}"


def wrap_user_notice(text: str) -> str:
    return textwrap.dedent(text).strip()


def _scan_balanced_json_object(text: str, start: int) -> str | None:
    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(text)):
        char = text[index]
        if escaped:
            escaped = False
            continue
        if char == "\\" and in_string:
            escaped = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
            if depth < 0:
                return None
    return None
