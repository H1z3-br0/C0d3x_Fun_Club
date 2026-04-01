from __future__ import annotations

import pytest

from ctf_swarm.agents import AgentProtocolError, _validate_master_plan
from ctf_swarm.utils import extract_json_object


def test_extract_json_object_raises_on_invalid_json() -> None:
    with pytest.raises(ValueError):
        extract_json_object("no json here")


def test_agent_protocol_error_for_invalid_executor_status() -> None:
    from ctf_swarm.agents import _validate_executor_response

    with pytest.raises(AgentProtocolError):
        _validate_executor_response(
            {
                "thought": "x",
                "status": "final",
                "result": {
                    "status": "wat",
                    "summary": "bad",
                    "evidence": [],
                    "artifacts": [],
                    "confidence": 0,
                },
            }
        )


def test_master_plan_defaults_missing_or_unknown_profile_to_base() -> None:
    payload = _validate_master_plan(
        {
            "analysis": "analysis",
            "task_summary": "summary",
            "network_required": False,
            "focus_recommendation": "focus",
            "cancel_hypotheses": [],
            "new_hypotheses": [
                {
                    "title": "inspect files",
                    "rationale": "fast triage",
                    "plan": ["run file", "run strings"],
                    "priority": 80,
                },
                {
                    "title": "test web path",
                    "rationale": "maybe web",
                    "plan": ["curl host"],
                    "priority": 70,
                    "profile": "unknown-profile",
                },
            ],
            "notes_for_support": "",
            "notes_for_user": "",
        }
    )

    assert payload["new_hypotheses"][0]["profile"] == "base"
    assert payload["new_hypotheses"][1]["profile"] == "base"
