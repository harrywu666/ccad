"""Runner Observer Agent 的提示资产加载器。"""

from __future__ import annotations

import json
from pathlib import Path

from services.audit_runtime.runner_observer_types import (
    RunnerObserverFeedSnapshot,
    RunnerObserverMemory,
)


_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts" / "runner_observer"


def _read_prompt_file(name: str) -> str:
    return (_PROMPT_DIR / name).read_text(encoding="utf-8").strip()


def load_runner_observer_agent_prompt() -> str:
    return _read_prompt_file("Agent.md")


def load_runner_observer_soul_prompt() -> str:
    return _read_prompt_file("soul.md")


def build_runner_observer_system_prompt() -> str:
    agent_prompt = load_runner_observer_agent_prompt()
    soul_prompt = load_runner_observer_soul_prompt()
    return f"{agent_prompt}\n\n---\n\n{soul_prompt}".strip()


def build_runner_observer_user_prompt(
    snapshot: RunnerObserverFeedSnapshot,
    memory: RunnerObserverMemory,
) -> str:
    payload = {
        "project_id": snapshot.project_id,
        "audit_version": snapshot.audit_version,
        "current_step": snapshot.current_step,
        "runtime_status": snapshot.runtime_status,
        "recent_events": snapshot.recent_events,
        "current_risk_signals": snapshot.current_risk_signals,
        "available_actions": snapshot.available_actions,
        "memory": {
            "project_summary": memory.project_summary,
            "current_focus": memory.current_focus,
            "recent_events": memory.recent_events,
            "intervention_history": memory.intervention_history,
        },
    }
    return (
        "请作为项目级 Runner Observer Agent，对当前审图现场做一次结构化判断。\n"
        "你必须只返回 JSON 对象，不要 markdown，不要解释。\n"
        "JSON 字段固定为："
        '{"summary":"","risk_level":"low|medium|high","suggested_action":"observe_only|broadcast_update|cancel_turn|restart_subsession|rerun_current_step|mark_needs_review","reason":"","should_intervene":false,"confidence":0.0,"user_facing_broadcast":""}\n'
        "现场数据如下：\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )


__all__ = [
    "build_runner_observer_system_prompt",
    "build_runner_observer_user_prompt",
    "load_runner_observer_agent_prompt",
    "load_runner_observer_soul_prompt",
]
