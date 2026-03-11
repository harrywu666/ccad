"""Runner 对外播报整理。"""

from __future__ import annotations

from typing import Any, Dict

from services.audit_runtime.runner_types import RunnerSubsession, RunnerTurnRequest


def build_runner_broadcast_message(
    request: RunnerTurnRequest,
    subsession: RunnerSubsession,
    *,
    state: str,
    meta: Dict[str, Any] | None = None,
) -> str:
    del subsession  # 当前版本先只根据请求和状态播报。
    normalized_state = str(state or "progress").strip().lower() or "progress"
    payload = dict(request.meta or {})
    if meta:
        payload.update(meta)

    if normalized_state in {"started", "progress", "streaming", "completed"}:
        return _progress_message(request, payload)
    if normalized_state == "waiting":
        return f"{_progress_message(request, payload)}，这一组图纸分析时间较长，Runner 正在继续等待"
    if normalized_state == "repairing":
        return f"{_agent_name(request)} 的输出格式不太稳定，Runner 正在自动整理"
    if normalized_state == "retrying":
        return f"{_agent_name(request)} 这一步刚刚卡住，Runner 正在重试"
    if normalized_state in {"deferred", "needs_review"}:
        return f"{_agent_name(request)} 这一步暂时还没拿到稳定结果，Runner 先记下并继续处理后续步骤"
    return f"{_agent_name(request)} 正在继续处理当前步骤"


def build_runner_broadcast_from_agent_report(agent_name: str, report) -> str:  # noqa: ANN001
    name = str(agent_name or "审图系统").strip() or "审图系统"
    blocking_issues = list(getattr(report, "blocking_issues", None) or [])
    help_request = str(getattr(report, "runner_help_request", "") or "").strip()
    next_action = str(getattr(report, "next_recommended_action", "") or "").strip()
    if blocking_issues:
        if help_request == "restart_subsession":
            return f"{name} 这批结果有点不稳，Runner 正在帮它重启当前子会话后继续推进"
        if next_action == "rerun_current_batch":
            return f"{name} 这批结果有点不稳，Runner 正在帮它重新跑这一批"
        return f"{name} 这一步暂时还没拿到稳定结果，Runner 正在接手整理"
    return f"{name} 已提交一批新的审查进展，Runner 正在继续汇总"


def _agent_name(request: RunnerTurnRequest) -> str:
    return str(request.agent_name or request.agent_key or "审图系统").strip() or "审图系统"


def _progress_message(request: RunnerTurnRequest, meta: Dict[str, Any]) -> str:
    turn_kind = str(request.turn_kind or "").strip().lower()
    run_mode = str(meta.get("run_mode") or "").strip().lower()
    candidate_index = _int_or_none(meta.get("candidate_index"))
    source_sheet_no = str(meta.get("source_sheet_no") or meta.get("candidate_source_sheet_no") or "").strip()
    target_sheet_no = str(meta.get("target_sheet_no") or meta.get("candidate_target_sheet_no") or "").strip()

    prefix_map = {
        "shadow_legacy": "影子旧路径：",
        "shadow_chief_review": "影子主审路径：",
        "chief_review": "主审路径：",
    }
    prefix = prefix_map.get(run_mode, "")

    if turn_kind == "relationship_candidate_review" and candidate_index is not None:
        base = f"{_agent_name(request)} 正在复核第 {candidate_index} 组候选关系"
        if source_sheet_no and target_sheet_no:
            return f"{prefix}{base}，当前核对 {source_sheet_no} 和 {target_sheet_no}"
        return f"{prefix}{base}"
    if turn_kind == "relationship_group_discovery":
        return f"{prefix}{_agent_name(request)} 正在整理值得继续复核的候选关系"
    if turn_kind in {"planning", "task_planning"}:
        return f"{prefix}{_agent_name(request)} 正在整理这次审图的基础信息"
    return f"{prefix}{_agent_name(request)} 正在继续推进当前审图步骤"


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


__all__ = [
    "build_runner_broadcast_from_agent_report",
    "build_runner_broadcast_message",
]
