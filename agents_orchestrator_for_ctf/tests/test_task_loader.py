from __future__ import annotations

from pathlib import Path

from ctf_swarm.task_loader import build_fallback_description, load_local_task


def test_load_local_task_with_generated_description(tmp_path: Path) -> None:
    (tmp_path / "sample.bin").write_bytes(b"\x00\x01")
    (tmp_path / "notes.txt").write_text("secret hint", encoding="utf-8")

    spec = load_local_task(str(tmp_path))

    assert spec.name == tmp_path.name
    assert spec.source == "local"
    assert "notes.txt" in spec.files
    assert "Описание было автоматически" in spec.description


def test_build_fallback_description_includes_files(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello", encoding="utf-8")
    description = build_fallback_description(tmp_path)
    assert "README.md" in description
