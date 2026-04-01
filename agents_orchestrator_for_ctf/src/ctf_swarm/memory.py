from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from .schemas import TaskState
from .utils import ensure_dir, utc_now


class MemoryStore:
    def __init__(self, workspace_root: Path) -> None:
        self.workspace_root = ensure_dir(workspace_root)
        self.db_path = self.workspace_root / "memory.sqlite3"
        self.connection = sqlite3.connect(self.db_path)
        self.connection.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cursor = self.connection.cursor()
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS solutions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_name TEXT NOT NULL,
                ctf_name TEXT,
                category TEXT,
                techniques_worked TEXT NOT NULL,
                techniques_failed TEXT NOT NULL,
                key_insight TEXT NOT NULL,
                flag TEXT NOT NULL,
                writeup_path TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        cursor.execute(
            """
            CREATE VIRTUAL TABLE IF NOT EXISTS solutions_fts
            USING fts5(
                task_name,
                ctf_name,
                category,
                techniques_worked,
                techniques_failed,
                key_insight,
                flag,
                content='solutions',
                content_rowid='id'
            )
            """
        )
        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS solutions_ai AFTER INSERT ON solutions
            BEGIN
                INSERT INTO solutions_fts(
                    rowid, task_name, ctf_name, category, techniques_worked,
                    techniques_failed, key_insight, flag
                ) VALUES (
                    new.id, new.task_name, new.ctf_name, new.category, new.techniques_worked,
                    new.techniques_failed, new.key_insight, new.flag
                );
            END
            """
        )
        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS solutions_ad AFTER DELETE ON solutions
            BEGIN
                INSERT INTO solutions_fts(solutions_fts, rowid, task_name, ctf_name, category, techniques_worked, techniques_failed, key_insight, flag)
                VALUES('delete', old.id, old.task_name, old.ctf_name, old.category, old.techniques_worked, old.techniques_failed, old.key_insight, old.flag);
            END
            """
        )
        cursor.execute(
            """
            CREATE TRIGGER IF NOT EXISTS solutions_au AFTER UPDATE ON solutions
            BEGIN
                INSERT INTO solutions_fts(solutions_fts, rowid, task_name, ctf_name, category, techniques_worked, techniques_failed, key_insight, flag)
                VALUES('delete', old.id, old.task_name, old.ctf_name, old.category, old.techniques_worked, old.techniques_failed, old.key_insight, old.flag);
                INSERT INTO solutions_fts(
                    rowid, task_name, ctf_name, category, techniques_worked,
                    techniques_failed, key_insight, flag
                ) VALUES (
                    new.id, new.task_name, new.ctf_name, new.category, new.techniques_worked,
                    new.techniques_failed, new.key_insight, new.flag
                );
            END
            """
        )
        self.connection.commit()

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        cleaned = query.strip()
        if not cleaned:
            return []
        cursor = self.connection.execute(
            """
            SELECT
                s.id,
                s.task_name,
                s.ctf_name,
                s.category,
                s.techniques_worked,
                s.techniques_failed,
                s.key_insight,
                s.flag,
                s.writeup_path,
                bm25(solutions_fts) AS score
            FROM solutions_fts
            JOIN solutions s ON s.id = solutions_fts.rowid
            WHERE solutions_fts MATCH ?
            ORDER BY score
            LIMIT ?
            """,
            (cleaned, limit),
        )
        return [dict(row) for row in cursor.fetchall()]

    def save_solution(self, task: TaskState) -> None:
        techniques_worked = "\n".join(
            finding.summary for finding in task.findings if finding.validated or finding.flag
        )
        techniques_failed = "\n".join(hypothesis.title for hypothesis in task.dead_hypotheses)
        key_insight = ""
        if task.findings:
            key_insight = task.findings[-1].summary
        elif task.completed_hypotheses:
            key_insight = task.completed_hypotheses[-1].last_summary

        self.connection.execute(
            """
            INSERT INTO solutions (
                task_name, ctf_name, category, techniques_worked, techniques_failed,
                key_insight, flag, writeup_path, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task.spec.name,
                task.spec.metadata.get("ctf_name"),
                task.spec.category,
                techniques_worked,
                techniques_failed,
                key_insight,
                task.flag or "",
                task.writeup_path,
                utc_now(),
            ),
        )
        self.connection.commit()

    def close(self) -> None:
        self.connection.close()
