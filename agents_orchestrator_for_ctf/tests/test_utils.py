from __future__ import annotations

import pytest

from ctf_swarm.utils import (
    extract_json_object,
    flag_format_to_regex,
    normalize_workspace_workdir,
    slugify,
)


def test_flag_format_to_regex() -> None:
    assert flag_format_to_regex("CTF{...}") == r"CTF\{[^}]+\}"


def test_slugify_normalizes_text() -> None:
    assert slugify(" Heap Challenge / 500 ") == "heap-challenge-500"


def test_extract_json_object_from_fenced_block() -> None:
    payload = extract_json_object(
        """
        analysis

        ```json
        {"status": "ok", "value": 123}
        ```
        """
    )
    assert payload == {"status": "ok", "value": 123}


def test_extract_json_object_handles_braces_inside_strings() -> None:
    payload = extract_json_object(
        '{"status":"ok","message":"use {curly} braces","nested":{"value":1}} trailing text'
    )
    assert payload == {
        "status": "ok",
        "message": "use {curly} braces",
        "nested": {"value": 1},
    }


def test_normalize_workspace_workdir_accepts_valid_paths() -> None:
    assert normalize_workspace_workdir("/workspace/task") == "/workspace/task"
    assert normalize_workspace_workdir("task/subdir") == "/workspace/task/subdir"
    assert normalize_workspace_workdir("artifacts/output") == "/workspace/artifacts/output"


def test_normalize_workspace_workdir_rejects_escape() -> None:
    with pytest.raises(ValueError):
        normalize_workspace_workdir("/workspace/task/../../etc")

    with pytest.raises(ValueError):
        normalize_workspace_workdir("../task")
