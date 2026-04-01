from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .llm import LLMGateway, UsageInfo
from .profiles import normalize_profile_name
from .prompts import (
    executor_system_prompt,
    executor_user_prompt,
    flag_validation_prompt,
    master_system_prompt,
    master_user_prompt,
    rotation_summary_system_prompt,
    rotation_summary_user_prompt,
    support_context_system_prompt,
    support_context_user_prompt,
    writeup_prompt,
)
from .schemas import Finding, Hypothesis, TaskState
from .utils import extract_json_object


class AgentProtocolError(RuntimeError):
    pass


@dataclass
class AgentResult:
    payload: dict[str, Any]
    usage: UsageInfo
    raw_text: str


class AgentService:
    def __init__(self, llm: LLMGateway) -> None:
        self.llm = llm

    async def master_plan(
        self,
        *,
        model: str,
        base_url: str | None,
        api_key: str | None,
        task: TaskState,
        flag_regex: str,
        event_summary: str,
        forced_message: str | None,
    ) -> AgentResult:
        response = await self.llm.complete(
            model=model,
            base_url=base_url,
            api_key=api_key,
            system_prompt=master_system_prompt(flag_regex),
            user_prompt=master_user_prompt(task, flag_regex, event_summary, forced_message),
        )
        payload = _validate_master_plan(extract_json_object(response.text))
        return AgentResult(payload=payload, usage=response.usage, raw_text=response.text)

    async def support_context(
        self,
        *,
        model: str,
        base_url: str | None,
        api_key: str | None,
        task: TaskState,
    ) -> AgentResult:
        response = await self.llm.complete(
            model=model,
            base_url=base_url,
            api_key=api_key,
            system_prompt=support_context_system_prompt(),
            user_prompt=support_context_user_prompt(task),
        )
        payload = _validate_support_context(extract_json_object(response.text))
        return AgentResult(payload=payload, usage=response.usage, raw_text=response.text)

    async def validate_flag(
        self,
        *,
        model: str,
        base_url: str | None,
        api_key: str | None,
        task: TaskState,
        finding: Finding,
        flag_regex: str,
    ) -> AgentResult:
        system_prompt, user_prompt = flag_validation_prompt(task, finding, flag_regex)
        response = await self.llm.complete(
            model=model,
            base_url=base_url,
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        payload = _validate_flag_validation(extract_json_object(response.text))
        return AgentResult(payload=payload, usage=response.usage, raw_text=response.text)

    async def writeup(
        self,
        *,
        model: str,
        base_url: str | None,
        api_key: str | None,
        task: TaskState,
    ) -> AgentResult:
        system_prompt, user_prompt = writeup_prompt(task)
        response = await self.llm.complete(
            model=model,
            base_url=base_url,
            api_key=api_key,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
        )
        payload = _validate_writeup(extract_json_object(response.text))
        return AgentResult(payload=payload, usage=response.usage, raw_text=response.text)

    async def rotation_summary(
        self,
        *,
        model: str,
        base_url: str | None,
        api_key: str | None,
        role: str,
        reason: str,
        tasks: list[TaskState],
    ) -> AgentResult:
        response = await self.llm.complete(
            model=model,
            base_url=base_url,
            api_key=api_key,
            system_prompt=rotation_summary_system_prompt(role),
            user_prompt=rotation_summary_user_prompt(role, reason, tasks),
        )
        payload = _validate_rotation_summary(extract_json_object(response.text))
        return AgentResult(payload=payload, usage=response.usage, raw_text=response.text)

    async def executor_turn(
        self,
        *,
        model: str,
        base_url: str | None,
        api_key: str | None,
        task: TaskState,
        hypothesis: Hypothesis,
        transcript: str,
        flag_regex: str,
    ) -> AgentResult:
        response = await self.llm.complete(
            model=model,
            base_url=base_url,
            api_key=api_key,
            system_prompt=executor_system_prompt(flag_regex),
            user_prompt=(
                executor_user_prompt(task, hypothesis, flag_regex)
                + "\n\nConversation transcript:\n"
                + transcript
            ),
        )
        payload = _validate_executor_response(extract_json_object(response.text))
        return AgentResult(payload=payload, usage=response.usage, raw_text=response.text)


def _validate_master_plan(payload: dict[str, Any]) -> dict[str, Any]:
    new_hypotheses = payload.get("new_hypotheses", [])
    if not isinstance(new_hypotheses, list):
        raise AgentProtocolError("master.new_hypotheses должен быть списком")
    validated_hypotheses = []
    for item in new_hypotheses:
        if not isinstance(item, dict):
            raise AgentProtocolError("Элемент new_hypotheses должен быть объектом")
        validated_hypotheses.append(
            {
                "title": _required_str(item, "title"),
                "rationale": _required_str(item, "rationale"),
                "plan": _required_list_of_str(item, "plan"),
                "priority": int(item.get("priority", 50)),
                "profile": normalize_profile_name(_optional_str(item.get("profile"))),
                "network_required": bool(item.get("network_required", False)),
                "tools": _optional_list_of_str(item.get("tools")) or ["shell"],
            }
        )
    return {
        "analysis": _required_str(payload, "analysis"),
        "task_summary": _required_str(payload, "task_summary"),
        "network_required": bool(payload.get("network_required", False)),
        "focus_recommendation": _required_str(payload, "focus_recommendation"),
        "cancel_hypotheses": _optional_list_of_str(payload.get("cancel_hypotheses")) or [],
        "new_hypotheses": validated_hypotheses,
        "notes_for_support": str(payload.get("notes_for_support", "")),
        "notes_for_user": str(payload.get("notes_for_user", "")),
    }


def _validate_support_context(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": _required_str(payload, "summary"),
        "memory_queries": _optional_list_of_str(payload.get("memory_queries")) or [],
        "relevant_techniques": _optional_list_of_str(payload.get("relevant_techniques")) or [],
        "possible_cves": _optional_list_of_str(payload.get("possible_cves")) or [],
        "notes_for_master": _required_str(payload, "notes_for_master"),
    }


def _validate_flag_validation(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "valid": bool(payload.get("valid", False)),
        "confidence": int(payload.get("confidence", 0)),
        "reasoning": _required_str(payload, "reasoning"),
        "writeup_summary": _required_str(payload, "writeup_summary"),
    }


def _validate_writeup(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": _required_str(payload, "title"),
        "markdown": _required_str(payload, "markdown"),
    }


def _validate_executor_response(payload: dict[str, Any]) -> dict[str, Any]:
    status = _required_str(payload, "status")
    if status not in {"command", "final"}:
        raise AgentProtocolError("executor.status должен быть command или final")
    result: dict[str, Any] = {
        "thought": _required_str(payload, "thought"),
        "status": status,
        "command": None,
        "result": None,
    }
    if status == "command":
        command = payload.get("command")
        if not isinstance(command, dict):
            raise AgentProtocolError("executor.command обязателен при status=command")
        result["command"] = {
            "cmd": _required_str(command, "cmd"),
            "reason": _required_str(command, "reason"),
            "timeout_seconds": int(command.get("timeout_seconds", 60)),
            "workdir": str(command.get("workdir", "/workspace/task")),
        }
    else:
        final = payload.get("result")
        if not isinstance(final, dict):
            raise AgentProtocolError("executor.result обязателен при status=final")
        final_status = _required_str(final, "status")
        if final_status not in {"success", "failed", "need_more_time", "flag_found"}:
            raise AgentProtocolError("executor.result.status имеет недопустимое значение")
        result["result"] = {
            "status": final_status,
            "summary": _required_str(final, "summary"),
            "evidence": _optional_list_of_str(final.get("evidence")) or [],
            "artifacts": _optional_list_of_str(final.get("artifacts")) or [],
            "flag": final.get("flag"),
            "confidence": int(final.get("confidence", 0)),
        }
    return result


def _validate_rotation_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "summary": _required_str(payload, "summary"),
        "key_risks": _optional_list_of_str(payload.get("key_risks")) or [],
        "next_actions": _optional_list_of_str(payload.get("next_actions")) or [],
    }


def _required_str(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise AgentProtocolError(f"Поле {key} должно быть непустой строкой")
    return value.strip()


def _required_list_of_str(payload: dict[str, Any], key: str) -> list[str]:
    value = payload.get(key)
    items = _optional_list_of_str(value)
    if not items:
        raise AgentProtocolError(f"Поле {key} должно быть непустым списком строк")
    return items


def _optional_list_of_str(value: Any) -> list[str] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise AgentProtocolError("Ожидался список строк")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise AgentProtocolError("Список должен содержать только строки")
        stripped = item.strip()
        if stripped:
            result.append(stripped)
    return result


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise AgentProtocolError("Ожидалась строка")
    stripped = value.strip()
    return stripped or None
