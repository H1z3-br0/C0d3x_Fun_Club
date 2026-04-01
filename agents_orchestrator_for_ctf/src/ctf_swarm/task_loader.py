from __future__ import annotations

from pathlib import Path
from typing import Any

from .schemas import TaskSpec
from .utils import (
    collect_text_snippets,
    load_yaml_file,
    read_text_file,
    slugify,
    summarize_directory,
)


def load_local_task(task_dir: str) -> TaskSpec:
    root = Path(task_dir).resolve()
    if not root.exists() or not root.is_dir():
        raise FileNotFoundError(f"Не найдена директория задачи: {root}")

    metadata = load_yaml_file(root / "task.yaml")
    description = _read_description(root)
    files = sorted(str(item.relative_to(root)) for item in root.rglob("*") if item.is_file())
    name = str(metadata.get("name") or root.name)

    return TaskSpec(
        task_id=slugify(name),
        name=name,
        task_dir=str(root),
        description=description,
        source="local",
        points=_as_int(metadata.get("points")),
        url=metadata.get("url"),
        host=metadata.get("host"),
        port=_as_int(metadata.get("port")),
        category=metadata.get("category"),
        metadata=metadata,
        files=files,
    )


def build_fallback_description(task_dir: Path) -> str:
    summary = summarize_directory(task_dir)
    snippets = collect_text_snippets(task_dir)
    return (
        "Описание было автоматически сгенерировано по содержимому директории.\n\n"
        f"Файлы:\n{summary}\n\n"
        f"Фрагменты:\n{snippets}"
    ).strip()


def _read_description(task_dir: Path) -> str:
    candidates = [task_dir / "task.txt"]
    candidates.extend(sorted(task_dir.glob("README.*")))
    for candidate in candidates:
        if candidate.exists():
            content = read_text_file(candidate, limit=50_000)
            if content.strip():
                return content.strip()
    return build_fallback_description(task_dir)


def _as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    return int(value)
