from __future__ import annotations

from pathlib import Path

from .schemas import TaskState
from .utils import ensure_dir


def save_writeup(task: TaskState, markdown: str) -> str:
    artifact_dir = ensure_dir(Path(task.artifact_dir))
    target = artifact_dir / "writeup.md"
    target.write_text(markdown.strip() + "\n", encoding="utf-8")
    return str(target)


def fallback_writeup(task: TaskState) -> str:
    finding_lines = "\n".join(f"- {finding.summary}" for finding in task.findings) or "- нет"
    success_lines = (
        "\n".join(f"- {item.title}: {item.last_summary}" for item in task.completed_hypotheses)
        or "- нет"
    )
    failed_lines = (
        "\n".join(f"- {item.title}: {item.last_summary}" for item in task.dead_hypotheses)
        or "- нет"
    )
    return f"""# Writeup: {task.spec.name}

## Что за таск

{task.spec.description}

## Что пробовали

### Сработало

{success_lines}

### Не сработало

{failed_lines}

## Ключевые находки

{finding_lines}

## Флаг

`{task.flag or "не найден"}`
"""
