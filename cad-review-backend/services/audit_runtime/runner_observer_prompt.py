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


def _consecutive_observe_only_count(memory: RunnerObserverMemory) -> int:
    count = 0
    for item in reversed(memory.recent_decisions):
        action = str(item.get("suggested_action") or "").strip()
        if action != "observe_only":
            break
        count += 1
    return count


def _build_decision_pressure(
    snapshot: RunnerObserverFeedSnapshot,
    memory: RunnerObserverMemory,
) -> str:
    observe_only_count = _consecutive_observe_only_count(memory)
    unstable_count = int(snapshot.risk_summary.get("output_validation_failed_count") or 0)
    unstable_streak = int(snapshot.risk_summary.get("output_unstable_streak") or 0)

    parts = []
    if observe_only_count >= 2:
        parts.append(f"你最近已经连续 {observe_only_count} 次仍以 observe_only 收敛。")
    if unstable_count >= 2:
        parts.append(f"最近同类输出不稳一共出现了 {unstable_count} 次。")
    if unstable_streak >= 2:
        parts.append(f"其中最近连续 {unstable_streak} 次都没有完全恢复。")
    if not parts:
        return "当前决策压力不高，可以继续以观察为主。"
    return "".join(parts) + "除非你能明确说明现场已经恢复，否则不要继续只给 observe_only。"


def build_runner_observer_user_prompt(
    snapshot: RunnerObserverFeedSnapshot,
    memory: RunnerObserverMemory,
) -> str:
    decision_pressure = _build_decision_pressure(snapshot, memory)
    payload = {
        "project_id": snapshot.project_id,
        "audit_version": snapshot.audit_version,
        "current_step": snapshot.current_step,
        "runtime_status": snapshot.runtime_status,
        "recent_events": snapshot.recent_events,
        "current_risk_signals": snapshot.current_risk_signals,
        "risk_summary": snapshot.risk_summary,
        "intervention_hint": snapshot.intervention_hint,
        "decision_pressure": decision_pressure,
        "available_actions": snapshot.available_actions,
        "memory": {
            "project_summary": memory.project_summary,
            "current_focus": memory.current_focus,
            "recent_events": memory.recent_events,
            "recent_decisions": memory.recent_decisions,
            "intervention_history": memory.intervention_history,
        },
    }
    return (
        "请作为项目级 Runner Observer Agent，对当前审图现场做一次结构化判断。\n"
        "你必须只返回 JSON 对象，不要 markdown，不要解释。\n"
        "判断原则补充：如果同类问题已经连续出现，或者你最近已经连续多次只给 observe_only，"
        "不要连续多次只给 observe_only；你需要认真考虑 broadcast_update、restart_subsession、mark_needs_review。\n"
        f"本轮决策压力提示：{decision_pressure}\n"
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
