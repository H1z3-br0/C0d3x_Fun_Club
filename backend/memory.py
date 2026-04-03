from __future__ import annotations

import hashlib
import math
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lancedb
import pyarrow as pa


EMBED_DIM = 256
TOKEN_RE = re.compile(r"[a-zA-Z0-9_]{2,}")


@dataclass
class MemoryRecord:
    id: str
    task_name: str
    ctf_name: str
    category: str
    techniques_worked: str
    techniques_failed: str
    key_insight: str
    flag: str
    writeup_path: str
    created_at: str
    text: str
    vector: list[float]


class MemoryStore:
    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(self.root_dir))
        self.table = self._get_or_create_table()

    def _get_or_create_table(self):
        if "solutions" in self.db.table_names():
            return self.db.open_table("solutions")
        schema = pa.schema(
            [
                ("id", pa.string()),
                ("task_name", pa.string()),
                ("ctf_name", pa.string()),
                ("category", pa.string()),
                ("techniques_worked", pa.string()),
                ("techniques_failed", pa.string()),
                ("key_insight", pa.string()),
                ("flag", pa.string()),
                ("writeup_path", pa.string()),
                ("created_at", pa.string()),
                ("text", pa.string()),
                ("vector", pa.list_(pa.float32())),
            ]
        )
        return self.db.create_table("solutions", schema=schema, data=[])

    def _embed(self, text: str) -> list[float]:
        vec = [0.0] * EMBED_DIM
        tokens = TOKEN_RE.findall(text.lower())
        for token in tokens:
            h = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(h, "little") % EMBED_DIM
            vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        cleaned = query.strip()
        if not cleaned:
            return []
        vec = self._embed(cleaned)
        results = self.table.search(vec).limit(limit).to_list()
        return [dict(item) for item in results]

    def save_solution(
        self,
        *,
        task_name: str,
        ctf_name: str = "",
        category: str = "",
        techniques_worked: str = "",
        techniques_failed: str = "",
        key_insight: str = "",
        flag: str = "",
        writeup_path: str = "",
    ) -> None:
        text = "\n".join(
            part
            for part in [task_name, ctf_name, category, techniques_worked, techniques_failed, key_insight]
            if part
        )
        record = MemoryRecord(
            id=str(uuid.uuid4()),
            task_name=task_name,
            ctf_name=ctf_name,
            category=category,
            techniques_worked=techniques_worked,
            techniques_failed=techniques_failed,
            key_insight=key_insight,
            flag=flag,
            writeup_path=writeup_path,
            created_at=datetime.now(timezone.utc).isoformat(),
            text=text,
            vector=self._embed(text or task_name),
        )
        self.table.add([record.__dict__])
