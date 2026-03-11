"""子 Agent 任务级恢复记忆。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Iterable, List


@dataclass(slots=True)
class TaskRecoveryMemory:
    """总控带记忆重启子 Agent 时使用的任务级快照。"""

    task_type: str
    task_ids: List[str]
    source_sheet_nos: List[str] = field(default_factory=list)
    target_sheet_nos: List[str] = field(default_factory=list)
    current_batch_key: str = ""
    last_error: str = ""
    restart_count: int = 0
    partial_outputs: List[dict[str, Any]] = field(default_factory=list)
    last_help_request: str = ""


def _safe_runtime_entries(trace_json: str | None) -> list[dict[str, Any]]:
    if not trace_json:
        return []
    try:
        payload = json.loads(trace_json)
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []
    runtime = payload.get("runtime")
    if not isinstance(runtime, list):
        return []
    return [item for item in runtime if isinstance(item, dict)]


def _extract_restart_count(tasks: Iterable[object]) -> int:
    max_count = 0
    for task in tasks:
        runtime_entries = _safe_runtime_entries(getattr(task, "trace_json", None))
        for entry in runtime_entries:
            if str(entry.get("event") or "").strip() != "master_recovery_attempted":
                continue
            try:
                max_count = max(max_count, int(entry.get("restart_count") or 0))
            except (TypeError, ValueError):
                continue
    return max_count


def _unique(values: Iterable[str | None]) -> list[str]:
    seen: list[str] = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in seen:
            seen.append(normalized)
    return seen


def build_task_recovery_memory(
    tasks: Iterable[object],
    *,
    task_type: str,
    current_batch_key: str,
    last_error: str,
    last_help_request: str = "",
    partial_outputs: list[dict[str, Any]] | None = None,
) -> TaskRecoveryMemory:
    task_list = list(tasks)
    return TaskRecoveryMemory(
        task_type=str(task_type or "").strip(),
        task_ids=[str(getattr(task, "id", "") or "").strip() for task in task_list if str(getattr(task, "id", "") or "").strip()],
        source_sheet_nos=_unique(getattr(task, "source_sheet_no", None) for task in task_list),
        target_sheet_nos=_unique(getattr(task, "target_sheet_no", None) for task in task_list),
        current_batch_key=str(current_batch_key or "").strip(),
        last_error=str(last_error or "").strip(),
        restart_count=_extract_restart_count(task_list),
        partial_outputs=list(partial_outputs or []),
        last_help_request=str(last_help_request or "").strip(),
    )


__all__ = [
    "TaskRecoveryMemory",
    "build_task_recovery_memory",
]
