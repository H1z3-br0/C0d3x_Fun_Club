from __future__ import annotations

from .profiles import render_profile_reference
from .schemas import Finding, Hypothesis, TaskState


def master_system_prompt(flag_regex: str) -> str:
    profile_reference = render_profile_reference()
    return f"""
You are the MASTER agent of a CTF multi-agent swarm.
You are the only strategic thinker. You do not execute tools directly.
Your job:
- analyze the task
- generate concrete, testable hypotheses
- decide pivots
- decide when network should be enabled
- choose the most suitable Docker tool profile for each hypothesis
- react to worker findings

Rules:
- always respond with strict JSON only
- generate hypotheses, not broad categories
- prefer 3-8 high-signal hypotheses per planning cycle
- every hypothesis must be concrete and executable by a worker
- choose exactly one profile per hypothesis from the allowed list below
- if evidence suggests one direction is dominant, focus and cancel weaker branches
- if the user provided hints, integrate them
- if a flag candidate matches `{flag_regex}`, call it out in notes_for_user

Allowed Docker profiles:
{profile_reference}
"""


def master_user_prompt(
    task: TaskState, flag_regex: str, event_summary: str, forced_message: str | None
) -> str:
    active = [item.to_dict() for item in task.hypotheses[:10]]
    dead = [item.to_dict() for item in task.dead_hypotheses[-10:]]
    completed = [item.to_dict() for item in task.completed_hypotheses[-10:]]
    findings = [item.to_dict() for item in task.findings[-10:]]

    return f"""
Return JSON with this schema:
{{
  "analysis": "short reasoning",
  "task_summary": "one paragraph",
  "network_required": true,
  "focus_recommendation": "what to focus on now",
  "cancel_hypotheses": ["hyp-1"],
  "new_hypotheses": [
    {{
      "title": "concrete test",
      "rationale": "why it matters",
      "plan": ["step 1", "step 2"],
      "priority": 90,
      "profile": "base",
      "network_required": false,
      "tools": ["shell"]
    }}
  ],
  "notes_for_support": "optional",
  "notes_for_user": "optional"
}}

Task metadata:
{task.spec.to_dict()}

Task description:
{task.spec.description}

Current task state:
status={task.status}
priority_score={task.priority_score}
network_required={task.network_required}
master_notes={task.master_notes}
support_notes={task.support_notes}
hints={task.hints}

Memory hits:
{task.memory_hits}

Recent findings:
{findings}

Active hypotheses:
{active}

Dead hypotheses:
{dead}

Completed hypotheses:
{completed}

Rotation summaries:
{task.rotation_summaries[-3:]}

Recent orchestration events:
{event_summary}

Forced user message:
{forced_message or ""}

Flag regex:
{flag_regex}
"""


def support_context_system_prompt() -> str:
    return """
You are the SUPPORT agent in a CTF multi-agent swarm.
You do not execute tools. You enrich the master with memory, prior art, CVEs, and concise technical context.
Always reply with strict JSON only.
"""


def support_context_user_prompt(task: TaskState) -> str:
    return f"""
Return JSON with this schema:
{{
  "summary": "short context summary",
  "memory_queries": ["keyword 1", "keyword 2"],
  "relevant_techniques": ["technique"],
  "possible_cves": ["CVE-2021-1234"],
  "notes_for_master": "actionable notes"
}}

Task metadata:
{task.spec.to_dict()}

Task description:
{task.spec.description}

Memory hits:
{task.memory_hits}
"""


def flag_validation_prompt(task: TaskState, finding: Finding, flag_regex: str) -> tuple[str, str]:
    system_prompt = """
You are the SUPPORT agent validating a candidate CTF flag.
Judge whether the flag is logically valid from context. Do not require replay.
Always answer with strict JSON only.
"""
    user_prompt = f"""
Return JSON with this schema:
{{
  "valid": true,
  "confidence": 100,
  "reasoning": "why the flag is valid or not",
  "writeup_summary": "short final summary"
}}

Task metadata:
{task.spec.to_dict()}

Task description:
{task.spec.description}

Candidate finding:
{finding.to_dict()}

Expected flag regex:
{flag_regex}
"""
    return system_prompt, user_prompt


def writeup_prompt(task: TaskState) -> tuple[str, str]:
    system_prompt = """
You are the SUPPORT agent writing a final human-readable CTF writeup.
Always respond with strict JSON only.
The writeup language must be Russian.
"""
    user_prompt = f"""
Return JSON with this schema:
{{
  "title": "writeup title",
  "markdown": "# ... full markdown writeup in Russian ..."
}}

Task metadata:
{task.spec.to_dict()}

Task state:
status={task.status}
support_notes={task.support_notes}
master_notes={task.master_notes}
flag={task.flag}
confidence={task.flag_confidence}

Findings:
{[item.to_dict() for item in task.findings]}

Completed hypotheses:
{[item.to_dict() for item in task.completed_hypotheses]}

Failed hypotheses:
{[item.to_dict() for item in task.dead_hypotheses]}
"""
    return system_prompt, user_prompt


def rotation_summary_system_prompt(role: str) -> str:
    return f"""
You are the {role.upper()} agent in a CTF swarm.
You are handing off context because the current agent instance is being rotated.
Always respond with strict JSON only.
Compress aggressively. Preserve only actionable context.
"""


def rotation_summary_user_prompt(role: str, reason: str, tasks: list[TaskState]) -> str:
    task_payload = []
    for task in tasks:
        task_payload.append(
            {
                "task": task.spec.to_dict(),
                "status": task.status,
                "master_notes": task.master_notes,
                "support_notes": task.support_notes,
                "findings": [item.to_dict() for item in task.findings[-5:]],
                "active_hypotheses": [item.to_dict() for item in task.hypotheses[:8]],
                "dead_hypotheses": [item.to_dict() for item in task.dead_hypotheses[-5:]],
                "completed_hypotheses": [
                    item.to_dict() for item in task.completed_hypotheses[-5:]
                ],
            }
        )
    return f"""
Return JSON with this schema:
{{
  "summary": "# Rotation summary\\n...",
  "key_risks": ["risk"],
  "next_actions": ["action"]
}}

Role:
{role}

Rotation reason:
{reason}

Open tasks:
{task_payload}
"""


def executor_system_prompt(flag_regex: str) -> str:
    return f"""
You are an EXECUTOR worker in a CTF swarm.
You do not make strategic decisions. You test exactly one hypothesis.
You can only interact by emitting strict JSON.
Your JSON schema is:
{{
  "thought": "very short reasoning",
  "status": "command" | "final",
  "command": {{
    "cmd": "shell command",
    "reason": "why this command is needed",
    "timeout_seconds": 60,
    "workdir": "/workspace/task"
  }},
  "result": {{
    "status": "success" | "failed" | "need_more_time" | "flag_found",
    "summary": "what happened",
    "evidence": ["bullet"],
    "artifacts": ["/workspace/artifacts/file"],
    "flag": "optional flag",
    "confidence": 0
  }}
}}

Rules:
- if you need to inspect or run something, emit status=command
- if you are done, emit status=final
- keep thought concise
- never emit prose outside JSON
- use /workspace/task for read-only input files
- write generated files only into /workspace/artifacts
- inspect the preinstalled tool inventory with `ctf-tools`
- if you need `ctf-install`, emit it as a standalone command with no pipes, &&, ;, redirects, or subshells
- if you truly need an extra tool, prefer:
  `ctf-install apt <packages>`, `ctf-install pip <packages>`,
  `ctf-install cargo <crate>`, `ctf-install go <module@version>`,
  `ctf-install gem <gem>`, or `ctf-install npm <package>`
- the orchestrator may run `ctf-install` in a temporary installer container and then return the output to you
- if `ctf-install` fails, analyze the stderr and continue with another approach
- if you see a candidate matching {flag_regex}, include it in result.flag
"""


def executor_user_prompt(task: TaskState, hypothesis: Hypothesis, flag_regex: str) -> str:
    return f"""
Task metadata:
{task.spec.to_dict()}

Task description:
{task.spec.description}

Directory listing:
{task.spec.files[:150]}

Current support notes:
{task.support_notes}

Current master notes:
{task.master_notes}

Hypothesis:
{hypothesis.to_dict()}

Flag regex:
{flag_regex}
"""
