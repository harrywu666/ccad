"""审计任务编排器。"""

from __future__ import annotations

import asyncio
from collections import defaultdict
import json
import logging
import os
from dataclasses import replace
import inspect
from types import SimpleNamespace

from database import SessionLocal
from domain.sheet_normalization import normalize_sheet_no
from models import AuditResult, SheetContext, SheetEdge
from services.audit_runtime.cancel_registry import (
    AuditCancellationRequested,
    clear_cancel_request,
    is_cancel_requested,
)
from services.audit import audit_dimensions, audit_indexes, audit_materials
from services.audit.persistence import add_and_commit
from services.audit_service import match_three_lines
from services.audit_runtime.evidence_planner import build_default_evidence_policy
from services.audit_runtime.hot_sheet_registry import HotSheetRegistry
from services.audit_runtime.visual_budget import VisualBudget, set_active_visual_budget
from services.audit_runtime.state_transitions import (
    append_result_upsert_events,
    append_result_summary_event,
    append_run_event,
    load_tasks,
    mark_running_tasks_failed,
    progress_by_task,
    set_project_status,
    set_task_status_batch,
    task_group_pairs,
    task_group_source_sheets,
    update_run_progress,
)
from services.audit_runtime.master_agent_recovery import (
    MAX_SUBAGENT_RESTARTS,
    can_retry_subagent,
    record_recovery_attempt,
    record_recovery_exhausted,
    record_recovery_success,
)
from services.audit_runtime.task_recovery_memory import build_task_recovery_memory
from services.cache_service import increment_cache_version
from services.audit.relationship_discovery import (
    discover_relationships,
    discover_relationships_v2,
    save_ai_edges,
)
from services.context_service import build_sheet_contexts
from services.task_planner_service import build_audit_tasks

logger = logging.getLogger(__name__)

from services.audit_runtime.final_review_agent import run_final_review_agent


def _json_compatible(value):  # noqa: ANN001
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, default=str))
    except Exception:
        if isinstance(value, (str, int, float, bool)) or value is None:
            return value
        if isinstance(value, list):
            return [_json_compatible(item) for item in value]
        if isinstance(value, dict):
            return {str(key): _json_compatible(item) for key, item in value.items()}
        return str(value)


class AuditCancelledError(RuntimeError):
    """用户手动中断审核。"""


class AuditSupersededError(RuntimeError):
    """当前总控已被新的恢复线程接管。"""


def _append_master_event(
    project_id: str,
    audit_version: int,
    *,
    level: str,
    step_key: str,
    event_kind: str,
    progress_hint: int,
    message: str,
    meta: dict | None = None,
) -> None:
    payload = {
        "pipeline_mode": "chief_review",
        "orchestration_model": "chief_worker",
        "actor_role": "chief",
        "planner_source": "chief_agent",
        "prompt_source": "chief_agent",
        "compat_mode": "native_agent_runtime",
        **(meta or {}),
    }
    append_run_event(
        project_id,
        audit_version,
        level=level,
        step_key=step_key,
        agent_key="chief_review_agent",
        agent_name="主审 Agent",
        event_kind=event_kind,
        progress_hint=progress_hint,
        message=message,
        meta=payload,
    )


def _append_worker_event(
    project_id: str,
    audit_version: int,
    *,
    step_key: str,
    agent_key: str,
    agent_name: str,
    level: str,
    event_kind: str,
    progress_hint: int,
    message: str,
    meta: dict | None = None,
) -> None:
    append_run_event(
        project_id,
        audit_version,
        level=level,
        step_key=step_key,
        agent_key=agent_key,
        agent_name=agent_name,
        event_kind=event_kind,
        progress_hint=progress_hint,
        message=message,
        meta={
            "pipeline_mode": "chief_worker",
            "orchestration_model": "chief_worker",
            "actor_role": "worker",
            "skill_id": (
                str((meta or {}).get("skill_id") or "").strip()
                or {
                    "relationship_discovery": "node_host_binding",
                    "index": "index_reference",
                    "dimension": "spatial_consistency",
                    "material": "material_semantic_consistency",
                }.get(step_key, "")
            ),
            **(meta or {}),
        },
    )


def _append_final_review_decision_event(
    project_id: str,
    audit_version: int,
    *,
    assignment_id: str,
    assignment=None,  # noqa: ANN001
    worker_result,
    final_review_decision,
) -> None:
    decision = str(getattr(final_review_decision, "decision", "") or "").strip()
    decision_source = str(getattr(final_review_decision, "decision_source", "") or "").strip() or "rule_fallback"
    level = "info"
    if decision == "accepted":
        level = "success"
    elif decision in {"needs_more_evidence", "redispatch"}:
        level = "warning"
    _append_master_event(
        project_id,
        audit_version,
        level=level,
        step_key="chief_review",
        event_kind="final_review_decision",
        progress_hint=90,
        message=f"终审完成 {assignment_id or 'unknown-assignment'}：{decision}（{decision_source}）",
        meta={
            "assignment_id": assignment_id,
            "task_title": str(getattr(assignment, "task_title", "") or "").strip() or None,
            "review_intent": str(getattr(assignment, "review_intent", "") or "").strip() or None,
            "decision": decision,
            "decision_source": decision_source,
            "rationale": str(getattr(final_review_decision, "rationale", "") or "").strip(),
            "requires_grounding": bool(getattr(final_review_decision, "requires_grounding", True)),
            "worker_summary": str(getattr(worker_result, "summary", "") or "").strip(),
            "worker_confidence": float(getattr(worker_result, "confidence", 0.0) or 0.0),
            "worker_markdown_conclusion": str(getattr(worker_result, "markdown_conclusion", "") or "").strip(),
            "worker_evidence_bundle": _json_compatible(getattr(worker_result, "evidence_bundle", {}) or {}),
            "task_id": str(getattr(worker_result, "task_id", "") or "").strip(),
            "hypothesis_id": str(getattr(worker_result, "hypothesis_id", "") or "").strip(),
            "task_stage": "chief_recheck",
        },
    )


def _worker_step_key(worker_kind: str) -> str:
    mapping = {
        "node_host_binding": "relationship_discovery",
        "index_reference": "index",
        "material_semantic_consistency": "material",
        "elevation_consistency": "dimension",
        "spatial_consistency": "dimension",
    }
    return mapping.get(str(worker_kind or "").strip(), "dimension")


def _append_assignment_completed_event(
    project_id: str,
    audit_version: int,
    *,
    worker_task,
    worker_result,
) -> None:
    assignment_id = str((worker_result.meta or {}).get("assignment_id") or worker_task.id or "").strip()
    if not assignment_id:
        return
    visible_session_key = str((worker_result.meta or {}).get("visible_session_key") or f"assignment:{assignment_id}").strip()
    worker_kind = str(getattr(worker_result, "worker_kind", "") or getattr(worker_task, "worker_kind", "") or "").strip()
    summary = str(getattr(worker_result, "summary", "") or "").strip()
    status = str(getattr(worker_result, "status", "") or "").strip().lower() or "completed"
    targets = list(getattr(worker_task, "target_sheet_nos", []) or [])
    _append_worker_event(
        project_id,
        audit_version,
        step_key=_worker_step_key(worker_kind),
        agent_key=f"{worker_kind or 'worker'}_agent",
        agent_name="副审 Agent",
        level="success" if status in {"confirmed", "rejected"} else "warning",
        event_kind="worker_assignment_completed",
        progress_hint=60,
        message=summary or "副审任务已完成，等待主审继续处理",
        meta={
            "assignment_id": assignment_id,
            "task_title": str(getattr(worker_task, "objective", "") or "").strip() or None,
            "visible_session_key": visible_session_key,
            "session_key": str((worker_result.meta or {}).get("session_key") or getattr(worker_task, "session_key", "") or "").strip() or None,
            "skill_id": worker_kind,
            "worker_kind": worker_kind,
            "worker_result_status": status,
            "summary": summary,
            "confidence": float(getattr(worker_result, "confidence", 0.0) or 0.0),
            "markdown_conclusion": str(getattr(worker_result, "markdown_conclusion", "") or "").strip(),
            "evidence_bundle": _json_compatible(getattr(worker_result, "evidence_bundle", {}) or {}),
            "source_sheet_no": getattr(worker_task, "source_sheet_no", None),
            "target_sheet_no": targets[0] if targets else None,
            "target_sheet_nos": targets,
            "task_stage": "worker_skill_execution",
        },
    )


def _run_with_session(callback):  # noqa: ANN001
    db = SessionLocal()
    try:
        return callback(db)
    finally:
        db.close()


def _isolate_stage_failure(
    project_id: str,
    audit_version: int,
    *,
    step_key: str,
    agent_key: str,
    agent_name: str,
    task_ids: list[str],
    progress_hint: int,
    note: str,
    exc: Exception,
) -> None:
    set_task_status_batch(
        project_id,
        audit_version,
        task_ids,
        "failed",
        note=note,
    )
    _append_worker_event(
        project_id,
        audit_version,
        step_key=step_key,
        agent_key=agent_key,
        agent_name=agent_name,
        level="warning",
        event_kind="warning",
        progress_hint=progress_hint,
        message=f"{agent_name} 这一段暂时没有跑稳，Runner 已记录局部故障并继续推进后续检查",
        meta={"error": str(exc), "isolated_failure": True},
    )


def _batch_key_for_tasks(task_type: str, tasks: list) -> str:  # noqa: ANN001
    if task_type == "dimension":
        pairs = [f"{(task.source_sheet_no or '').strip()}->{(task.target_sheet_no or '').strip()}" for task in tasks]
        normalized = [item for item in pairs if item != "->"]
        return f"{task_type}:{'|'.join(normalized)}"
    sheets = [str(getattr(task, "source_sheet_no", "") or "").strip() for task in tasks]
    normalized = [item for item in sheets if item]
    return f"{task_type}:{'|'.join(normalized)}"


def _recover_stage_once(
    project_id: str,
    audit_version: int,
    *,
    step_key: str,
    agent_key: str,
    agent_name: str,
    tasks: list,  # noqa: ANN001
    run_stage,  # noqa: ANN001
    progress_hint: int,
    task_type: str,
    exc: Exception,
):
    memory = build_task_recovery_memory(
        tasks,
        task_type=task_type,
        current_batch_key=_batch_key_for_tasks(task_type, tasks),
        last_error=str(exc),
        last_help_request="restart_subsession",
    )
    last_exc = exc

    while can_retry_subagent(memory):
        restart_count = record_recovery_attempt(
            project_id,
            audit_version,
            memory=memory,
            reason=str(last_exc),
        )
        _append_master_event(
            project_id,
            audit_version,
            level="warning",
            step_key=step_key,
            event_kind="master_recovery_requested",
            progress_hint=progress_hint,
            message=f"总控规划Agent 正在带着这批任务的记忆重启 {agent_name}，这是第 {restart_count} 次补救",
            meta={
                "task_type": task_type,
                "restart_count": restart_count,
                "max_restarts": MAX_SUBAGENT_RESTARTS,
                "task_ids": memory.task_ids,
                "current_batch_key": memory.current_batch_key,
            },
        )
        try:
            result = run_stage()
        except Exception as retry_exc:  # noqa: BLE001
            last_exc = retry_exc
            memory = replace(
                memory,
                restart_count=restart_count,
                last_error=str(retry_exc),
            )
            continue

        record_recovery_success(
            project_id,
            audit_version,
            memory=replace(memory, restart_count=restart_count),
            restart_count=restart_count,
        )
        _append_master_event(
            project_id,
            audit_version,
            level="success",
            step_key=step_key,
            event_kind="master_recovery_succeeded",
            progress_hint=progress_hint,
            message=f"总控规划Agent 已带着记忆重启 {agent_name}，这批任务继续从原上下文推进",
            meta={
                "task_type": task_type,
                "restart_count": restart_count,
                "task_ids": memory.task_ids,
                "current_batch_key": memory.current_batch_key,
            },
        )
        return result, True

    final_memory = replace(memory, last_error=str(last_exc))
    record_recovery_exhausted(
        project_id,
        audit_version,
        memory=final_memory,
        reason=str(last_exc),
    )
    _append_master_event(
        project_id,
        audit_version,
        level="warning",
        step_key=step_key,
        event_kind="master_recovery_exhausted",
        progress_hint=progress_hint,
        message=f"总控规划Agent 已多次尝试恢复 {agent_name}，这批任务暂时跳过，整轮继续推进",
        meta={
            "task_type": task_type,
            "restart_count": final_memory.restart_count,
            "max_restarts": MAX_SUBAGENT_RESTARTS,
            "task_ids": final_memory.task_ids,
            "current_batch_key": final_memory.current_batch_key,
            "error": str(last_exc),
        },
    )
    return [], False


def _raise_if_cancelled(
    project_id: str,
    *,
    worker_generation: int | None = None,
    is_current_worker=None,  # noqa: ANN001
) -> None:
    if worker_generation is not None and callable(is_current_worker):
        try:
            if not bool(is_current_worker(project_id, int(worker_generation))):
                raise AuditSupersededError("当前总控已被新的恢复线程接管")
        except AuditSupersededError:
            raise
        except Exception:
            pass
    if is_cancel_requested(project_id):
        raise AuditCancelledError("用户手动中断审核")


def _orchestrator_v2_enabled() -> bool:
    return str(os.getenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _chief_review_enabled() -> bool:
    return str(os.getenv("AUDIT_CHIEF_REVIEW_ENABLED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _legacy_pipeline_allowed() -> bool:
    return str(os.getenv("AUDIT_LEGACY_PIPELINE_ALLOWED", "0")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _forced_legacy_pipeline_mode() -> str | None:
    raw = str(os.getenv("AUDIT_FORCE_PIPELINE_MODE", "")).strip().lower()
    if raw in {"legacy", "v2"}:
        return raw
    return None


def resolve_pipeline_mode() -> str:
    forced_mode = _forced_legacy_pipeline_mode()
    if not _legacy_pipeline_allowed() or not forced_mode:
        return "chief_review"
    if forced_mode == "v2" and _orchestrator_v2_enabled():
        return "v2"
    return "legacy"


def _read_budget_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(0, value)


def _chief_finding_issue_type(finding_type: str) -> str:
    mapping = {
        "dim_mismatch": "dimension",
        "material_conflict": "material",
        "index_conflict": "index",
        "missing_ref": "relationship",
    }
    return mapping.get(str(finding_type or "").strip(), "chief_review")


def _normalized_scope_key(
    source_sheet_no: str,
    target_sheet_nos: list[str],
    worker_kind: str,
) -> tuple[str, tuple[str, ...], str]:
    return (
        normalize_sheet_no(source_sheet_no),
        tuple(
            sorted(
                {
                    normalize_sheet_no(item)
                    for item in list(target_sheet_nos or [])
                    if normalize_sheet_no(item)
                }
            )
        ),
        str(worker_kind or "").strip(),
    )


def _memory_scope_key(item: dict) -> tuple[str, tuple[str, ...], str]:
    context = dict(item.get("context") or {})
    worker_kind = (
        str(item.get("worker_kind") or "").strip()
        or str(context.get("suggested_worker_kind") or "").strip()
    )
    return _normalized_scope_key(
        str(item.get("source_sheet_no") or "").strip(),
        [str(target).strip() for target in list(item.get("target_sheet_nos") or []) if str(target).strip()],
        worker_kind,
    )


def _build_hypothesis_blueprint(
    worker_kind: str,
    *,
    source_sheet_no: str,
    target_sheet_nos: list[str],
    target_types: list[str],
) -> tuple[str, str, float, dict]:
    target_label = ", ".join(target_sheet_nos[:3])
    if worker_kind == "node_host_binding":
        return (
            "节点归属复核",
            f"确认 {source_sheet_no} 中指向 {target_label} 的节点/详图是否挂对母图，并排除串图或误指",
            0.95,
            {
                "review_focus": "node_host_binding",
                "suspect_reason": "detail_target_detected",
                "suggested_worker_kind": worker_kind,
                "target_sheet_types": target_types,
            },
        )
    if worker_kind == "index_reference":
        return (
            "索引引用复核",
            f"确认 {source_sheet_no} 指向 {target_label} 的索引号、目标图号和引用关系是否一致",
            0.88,
            {
                "review_focus": "index_reference",
                "suspect_reason": "reference_target_detected",
                "suggested_worker_kind": worker_kind,
                "target_sheet_types": target_types,
            },
        )
    if worker_kind == "elevation_consistency":
        return (
            "标高一致性",
            f"核对 {source_sheet_no} 与 {target_label} 的标高、完成面和空间对应关系是否前后一致",
            0.84,
            {
                "review_focus": "elevation_consistency",
                "suspect_reason": "elevation_target_detected",
                "suggested_worker_kind": worker_kind,
                "target_sheet_types": target_types,
            },
        )
    return (
        "空间一致性",
        f"复核 {source_sheet_no} 与 {target_label} 的空间定位、尺寸边界和构件关系是否一致",
        0.72,
        {
            "review_focus": "spatial_consistency",
            "suspect_reason": "linked_target_detected",
            "suggested_worker_kind": worker_kind,
            "target_sheet_types": target_types,
        },
    )


def _build_memory_learning_record(
    hypothesis: dict,
    *,
    status: str,
    reasons: list[str] | None = None,
) -> dict:
    context = dict(hypothesis.get("context") or {})
    return {
        "id": str(hypothesis.get("id") or "").strip(),
        "topic": str(hypothesis.get("topic") or "").strip(),
        "objective": str(hypothesis.get("objective") or "").strip(),
        "source_sheet_no": str(hypothesis.get("source_sheet_no") or "").strip(),
        "target_sheet_nos": [
            str(item).strip()
            for item in list(hypothesis.get("target_sheet_nos") or [])
            if str(item).strip()
        ],
        "worker_kind": str(context.get("suggested_worker_kind") or hypothesis.get("worker_kind") or "").strip(),
        "status": status,
        "reasons": list(reasons or []),
    }


def _merge_unique_memory_records(existing: list[dict], additions: list[dict]) -> list[dict]:
    merged: list[dict] = []
    seen: set[tuple[str, tuple[str, ...], str]] = set()
    for item in [*existing, *additions]:
        key = _memory_scope_key(dict(item or {}))
        if not key[0] or not key[1] or not key[2] or key in seen:
            continue
        seen.add(key)
        merged.append(dict(item or {}))
    return merged


def _update_chief_review_memory(
    memory: dict,
    *,
    worker_results: list,
    findings: list,
    escalations: list[dict],
) -> dict:
    active_hypotheses = [dict(item or {}) for item in list(memory.get("active_hypotheses") or [])]
    existing_recheck_queue = [dict(item or {}) for item in list(memory.get("chief_recheck_queue") or [])]
    grouped_results: dict[str, list] = defaultdict(list)
    for item in worker_results:
        grouped_results[str(item.hypothesis_id or "").strip()].append(item)

    finding_ids = {
        str(getattr(item, "triggered_by", "") or "").strip()
        for item in findings
        if str(getattr(item, "triggered_by", "") or "").strip()
    }
    escalation_map: dict[str, list[str]] = defaultdict(list)
    for item in escalations:
        hypothesis_id = str(item.get("hypothesis_id") or "").strip()
        if not hypothesis_id:
            continue
        escalation_map[hypothesis_id].extend(
            [str(reason).strip() for reason in list(item.get("reasons") or []) if str(reason).strip()]
        )

    next_active: list[dict] = []
    resolved_additions: list[dict] = []
    false_positive_additions: list[dict] = []
    chief_recheck_additions: list[dict] = []

    for hypothesis in active_hypotheses:
        hypothesis_id = str(hypothesis.get("id") or "").strip()
        if not hypothesis_id:
            continue
        results = grouped_results.get(hypothesis_id, [])
        statuses = {str(item.status or "").strip().lower() for item in results}
        if hypothesis_id in escalation_map:
            context = dict(hypothesis.get("context") or {})
            context["needs_chief_review"] = True
            context["chief_recheck_reasons"] = sorted(set(escalation_map[hypothesis_id]))
            chief_recheck_additions.append(
                {
                    **hypothesis,
                    "priority": max(float(hypothesis.get("priority") or 0.5), 0.98),
                    "worker_kind": str(
                        hypothesis.get("worker_kind")
                        or context.get("suggested_worker_kind")
                        or ""
                    ).strip(),
                    "context": context,
                }
            )
            continue
        if hypothesis_id in finding_ids:
            resolved_additions.append(
                _build_memory_learning_record(
                    hypothesis,
                    status="confirmed",
                    reasons=sorted(statuses) or ["confirmed"],
                )
            )
            continue
        if results and statuses and statuses.issubset({"rejected", "dismissed"}):
            false_positive_additions.append(
                _build_memory_learning_record(
                    hypothesis,
                    status="false_positive",
                    reasons=sorted(statuses),
                )
            )
            continue
        if not results:
            next_active.append(hypothesis)
            continue
        if any(item.escalate_to_chief for item in results) or statuses & {"needs_review", "conflict"}:
            context = dict(hypothesis.get("context") or {})
            context["needs_chief_review"] = True
            context["chief_recheck_reasons"] = sorted(
                statuses & {"needs_review", "conflict"} or {"needs_review"}
            )
            chief_recheck_additions.append(
                {
                    **hypothesis,
                    "priority": max(float(hypothesis.get("priority") or 0.5), 0.96),
                    "worker_kind": str(
                        hypothesis.get("worker_kind")
                        or context.get("suggested_worker_kind")
                        or ""
                    ).strip(),
                    "context": context,
                }
            )
            continue
        next_active.append(hypothesis)

    return {
        **memory,
        "active_hypotheses": next_active,
        "chief_recheck_queue": _merge_unique_memory_records(
            existing_recheck_queue,
            chief_recheck_additions,
        ),
        "resolved_hypotheses": _merge_unique_memory_records(
            list(memory.get("resolved_hypotheses") or []),
            resolved_additions,
        ),
        "false_positive_hints": _merge_unique_memory_records(
            list(memory.get("false_positive_hints") or []),
            false_positive_additions,
        ),
    }


def _build_default_hypotheses(sheet_graph, *, memory: dict | None = None) -> list[dict]:  # noqa: ANN001
    from services.audit_runtime.chief_review_planner import build_default_chief_hypotheses

    hypotheses, _ = build_default_chief_hypotheses(
        sheet_graph=sheet_graph,
        memory=memory,
    )
    return hypotheses


def _build_chief_sheet_graph_semantic_runner(*, project_id: str, audit_version: int):
    from services.ai_service import call_kimi
    from services.audit_runtime.sheet_graph_semantic_builder import _fallback_semantic_result
    from services.audit_runtime.runtime_prompt_assembler import assemble_agent_runtime_prompt

    def _runner(candidates: dict) -> dict:
        payload_json = json.dumps(candidates, ensure_ascii=False, indent=2)
        prompt_bundle = assemble_agent_runtime_prompt(
            agent_id="chief_review",
            task_context={
                "project_id": project_id,
                "audit_version": audit_version,
                "sheet_graph_candidates": candidates,
            },
            prompt_source="chief_agent",
            user_prompt_override=(
                "你现在只负责图纸语义建图，不负责输出审图问题。\n"
                "请根据输入候选信息判断每张图的最终类型，以及跨图链接关系。\n"
                "只返回 JSON 对象，字段固定为：\n"
                '{"sheet_types":{"图号":"plan|ceiling|elevation|detail|reference|unknown"},'
                '"linked_targets":{"图号":["目标图号"]},"node_hosts":{"图号":["母图图号"]}}\n\n'
                f"输入数据：\n{payload_json}\n"
            ),
        )
        try:
            result = asyncio.run(
                call_kimi(
                    prompt_bundle.system_prompt,
                    prompt_bundle.user_prompt,
                    temperature=0.1,
                    max_tokens=4096,
                )
            )
        except Exception:
            return _fallback_semantic_result(candidates)
        if not isinstance(result, dict):
            return _fallback_semantic_result(candidates)
        return {
            "sheet_types": dict(result.get("sheet_types") or {}),
            "linked_targets": dict(result.get("linked_targets") or {}),
            "node_hosts": dict(result.get("node_hosts") or {}),
        }

    return _runner


def _build_chief_sheet_graph(
    *,
    project_id: str,
    audit_version: int,
    sheet_contexts: list,
    sheet_edges: list,
):
    from services.audit_runtime.sheet_graph_builder import build_sheet_graph

    return build_sheet_graph(
        sheet_contexts=sheet_contexts,
        sheet_edges=sheet_edges,
        llm_runner=_build_chief_sheet_graph_semantic_runner(
            project_id=project_id,
            audit_version=audit_version,
        ),
    )


async def _default_chief_worker_runner(task):  # noqa: ANN001
    from services.audit_runtime.review_worker_runtime import run_native_review_worker
    from services.audit_runtime.review_task_schema import WorkerResultCard

    def _run_compatibility_wrapper(db):  # noqa: ANN001
        project_id = str(task.context.get("project_id") or "").strip()
        audit_version = int(task.context.get("audit_version") or 0)
        worker_kind = str(task.worker_kind or "").strip()

        if worker_kind in {"elevation_consistency", "spatial_consistency"}:
            from services.audit.dimension_audit import run_dimension_worker_wrapper

            return run_dimension_worker_wrapper(project_id, audit_version, db, task)
        if worker_kind == "material_semantic_consistency":
            from services.audit.material_audit import run_material_worker_wrapper

            return run_material_worker_wrapper(project_id, audit_version, db, task)
        if worker_kind == "index_reference":
            from services.audit.index_audit import run_index_worker_wrapper

            return run_index_worker_wrapper(project_id, audit_version, db, task)
        if worker_kind == "node_host_binding":
            from services.audit.relationship_discovery import run_relationship_worker_wrapper

            return run_relationship_worker_wrapper(project_id, audit_version, db, task)
        return None

    db = SessionLocal()
    try:
        native_result = await run_native_review_worker(task=task, db=db)
        if native_result is not None:
            return native_result
        compatibility_result = _run_compatibility_wrapper(db)
        if compatibility_result is not None:
            return compatibility_result
        return WorkerResultCard(
            task_id=task.id,
            hypothesis_id=task.hypothesis_id,
            worker_kind=task.worker_kind,
            status="needs_review",
            confidence=0.35,
            summary=f"{task.worker_kind} 未注册到 worker skill 执行器，已回主审处理",
            escalate_to_chief=True,
            meta={
                "compat_mode": "worker_skill_required",
                "execution_mode": "worker_skill",
                "sheet_no": task.source_sheet_no,
                "location": task.objective,
                "rule_id": "CHIEF-SKILL-MISSING",
                "evidence_pack_id": "chief_review_pack",
            },
        )
    except Exception as exc:  # noqa: BLE001
        return WorkerResultCard(
            task_id=task.id,
            hypothesis_id=task.hypothesis_id,
            worker_kind=task.worker_kind,
            status="needs_review",
            confidence=0.2,
            summary=f"{task.worker_kind} worker skill 执行异常：{exc}",
            escalate_to_chief=True,
            meta={
                "compat_mode": "worker_skill_error",
                "execution_mode": "worker_skill",
                "sheet_no": task.source_sheet_no,
                "location": task.objective,
                "rule_id": "CHIEF-WORKER-ERROR",
                "evidence_pack_id": "chief_review_pack",
                "error": str(exc),
            },
        )
    finally:
        db.close()


async def _dispatch_review_assignments_incrementally(
    *,
    chief_session,
    assignments: list,
    worker_runner=None,  # noqa: ANN001
    on_assignment_completed=None,  # noqa: ANN001
):
    from services.audit_runtime.chief_dispatch_policy import evaluate_dispatch_state
    from services.audit_runtime.review_worker_pool import ReviewWorkerPool

    pending_assignments = list(assignments)
    pool = ReviewWorkerPool(
        max_concurrency=1,
        worker_runner=worker_runner or _default_chief_worker_runner,
    )
    worker_results = []

    while True:
        decision = evaluate_dispatch_state(
            pending_assignments=pending_assignments,
            active_worker_count=0,
            final_review_pending_count=0,
            has_new_directions=False,
        )
        if decision.should_stop:
            break
        if decision.should_wait:
            await asyncio.sleep(0)
            continue
        next_assignment = chief_session.next_assignment(pending_assignments)
        if next_assignment is None:
            break
        pending_assignments.pop(0)
        worker_task = chief_session.build_worker_task_from_assignment(next_assignment)
        batch_results = await pool.run_batch([worker_task]) or []
        for item in batch_results:
            _append_assignment_completed_event(
                chief_session.project_id,
                chief_session.audit_version,
                worker_task=worker_task,
                worker_result=item,
            )
            if callable(on_assignment_completed):
                on_assignment_completed(
                    assignment=next_assignment,
                    worker_task=worker_task,
                    worker_result=item,
                )
        worker_results.extend(batch_results)

    return worker_results


def _build_redispatch_hypothesis(assignment, rationale: str) -> dict:  # noqa: ANN001
    return {
        "id": str(getattr(assignment, "assignment_id", "") or "").split("::", 1)[0],
        "topic": str(getattr(assignment, "review_intent", "") or "终审补派").strip(),
        "objective": str(getattr(assignment, "task_title", "") or "").strip(),
        "source_sheet_no": str(getattr(assignment, "source_sheet_no", "") or "").strip(),
        "target_sheet_nos": list(getattr(assignment, "target_sheet_nos", []) or []),
        "priority": float(getattr(assignment, "priority", 0.9) or 0.9),
        "context": {
            "suggested_worker_kind": str(getattr(assignment, "review_intent", "") or "").strip(),
            "needs_chief_review": True,
            "final_review_rationale": rationale,
        },
    }


def _route_worker_results_back_to_chief_review(
    *,
    assignments: list,
    worker_results: list[WorkerResultCard],
):
    assignment_by_id = {
        str(getattr(item, "assignment_id", "") or "").strip(): item
        for item in list(assignments or [])
        if str(getattr(item, "assignment_id", "") or "").strip()
    }
    approved_issue_candidates: list[dict] = []
    chief_recheck_queue: list[dict] = []
    chief_rejections: list[dict] = []
    decisions: list[dict] = []

    for result in worker_results:
        assignment_id = str(
            (result.meta or {}).get("assignment_id")
            or (result.evidence_bundle or {}).get("assignment_id")
            or result.task_id
            or ""
        ).strip()
        assignment = assignment_by_id.get(assignment_id)
        if assignment is None:
            chief_rationale = "副审结果缺少主审派单上下文，不能直接进终审，必须回主审补齐。"
            record = {
                "assignment_id": assignment_id,
                "assignment": None,
                "worker_result": result,
                "chief_decision": "recheck_missing_assignment",
                "chief_rationale": chief_rationale,
            }
            decisions.append(record)
            chief_recheck_queue.append(record)
            continue

        evidence_bundle = dict(result.evidence_bundle or {})
        result_kind = str(evidence_bundle.get("result_kind") or "").strip().lower()
        status = str(result.status or "").strip().lower()

        chief_decision = "recheck"
        chief_rationale = "副审返回内容还需要主审继续判断。"
        if result_kind == "relationship_signal":
            chief_decision = "reject_as_signal"
            chief_rationale = "副审返回的是关系线索，只能作为主审参考，不能直接当成问题提交。"
        elif result_kind == "non_issue" or status in {"rejected", "dismissed"}:
            chief_decision = "reject_as_non_issue"
            chief_rationale = "副审已明确未发现问题，这条不进入最终问题通道。"
        elif status in {"needs_review", "conflict"} or bool(result.escalate_to_chief):
            chief_decision = "recheck"
            chief_rationale = "副审结论还不稳定，主审需要继续复核或补派。"
        elif result_kind == "issue" and status == "confirmed":
            chief_decision = "submit_to_final_review"
            chief_rationale = "主审认可这是一条正式问题候选，提交终审做程序入库前校验。"

        record = {
            "assignment_id": assignment_id,
            "assignment": assignment,
            "worker_result": result,
            "chief_decision": chief_decision,
            "chief_rationale": chief_rationale,
        }
        decisions.append(record)
        if chief_decision == "submit_to_final_review":
            approved_issue_candidates.append(record)
        elif chief_decision == "recheck":
            chief_recheck_queue.append(record)
        else:
            chief_rejections.append(record)

    return approved_issue_candidates, chief_recheck_queue, chief_rejections, decisions


def _route_worker_results_through_final_review(
    *,
    chief_review_records: list[dict],
    project_id: str | None = None,
    audit_version: int | None = None,
    chief_session=None,  # noqa: ANN001
    memory: dict | None = None,
):
    accepted: list[WorkerResultCard] = []
    escalations: list[dict] = []
    decisions: list[dict] = []
    redispatch_assignments: list = []

    for chief_review_record in chief_review_records:
        assignment_id = str(chief_review_record.get("assignment_id") or "").strip()
        assignment = chief_review_record.get("assignment")
        result = chief_review_record.get("worker_result")
        if assignment is None:
            if result is not None:
                accepted.append(result)
            continue
        decision = run_final_review_agent(
            assignment=assignment,
            worker_result=result,
        )
        if project_id and audit_version is not None:
            _append_final_review_decision_event(
                project_id,
                int(audit_version),
                assignment_id=assignment_id,
                assignment=assignment,
                worker_result=result,
                final_review_decision=decision,
            )
        decisions.append(
            {
                "assignment_id": assignment_id,
                "assignment": assignment,
                "worker_result": result,
                "chief_decision": chief_review_record.get("chief_decision"),
                "chief_rationale": chief_review_record.get("chief_rationale"),
                "final_review_decision": decision,
            }
        )
        if decision.decision == "accepted":
            accepted.append(result)
            continue
        if decision.decision in {"needs_more_evidence", "redispatch"}:
            escalations.append(
                {
                    "hypothesis_id": result.hypothesis_id,
                    "task_id": result.task_id,
                    "assignment_id": assignment_id,
                    "escalate_to_chief": True,
                    "reasons": [decision.decision],
                    "rationale": decision.rationale,
                }
            )
            if decision.decision == "redispatch" and chief_session is not None:
                redispatch_memory = dict(memory or {})
                redispatch_memory["active_hypotheses"] = [
                    _build_redispatch_hypothesis(assignment, decision.rationale)
                ]
                redispatch_assignments.extend(chief_session.plan_assignments(memory=redispatch_memory))
            continue
    return accepted, escalations, decisions, redispatch_assignments


def _persist_chief_findings(project_id: str, audit_version: int, findings: list) -> None:  # noqa: ANN001
    if not findings:
        return
    rows = [
        AuditResult(
            project_id=project_id,
            audit_version=audit_version,
            type=_chief_finding_issue_type(item.finding_type),
            severity=item.severity,
            sheet_no_a=item.sheet_no,
            location=item.location,
            rule_id=item.rule_id,
            finding_type=item.finding_type,
            finding_status=item.status,
            source_agent=item.source_agent,
            evidence_pack_id=item.evidence_pack_id,
            review_round=item.review_round,
            triggered_by=item.triggered_by,
            confidence=item.confidence,
            description=item.description,
            evidence_json=json.dumps({"finding": item.model_dump()}, ensure_ascii=False),
        )
        for item in findings
    ]
    db = SessionLocal()
    try:
        add_and_commit(db, rows)
        append_result_upsert_events(
            project_id,
            audit_version,
            issue_ids=[str(row.id) for row in rows if getattr(row, "id", None)],
        )
    finally:
        db.close()


def _final_issue_to_audit_result(
    final_issue,
    *,
    final_review_meta_by_assignment: dict[str, dict] | None = None,
) -> AuditResult:  # noqa: ANN001
    finding_type = str(getattr(final_issue, "finding_type", "") or "").strip()
    issue_type = _chief_finding_issue_type(finding_type)
    target_sheet_nos = list(getattr(final_issue, "target_sheet_nos", []) or [])
    anchors = [anchor.model_dump() for anchor in list(getattr(final_issue, "anchors", []) or [])]
    grounding = {
        "status": "grounded" if anchors else "missing",
        "anchor_count": len(anchors),
    }
    evidence_json = json.dumps(
        {
            "anchors": anchors,
            "grounding": grounding,
            "evidence_pack_id": getattr(final_issue, "evidence_pack_id", ""),
            "finding": final_issue.model_dump(),
            "final_review": dict(
                (final_review_meta_by_assignment or {}).get(
                    str(getattr(final_issue, "source_assignment_id", "") or "").strip(),
                    {},
                )
            ),
        },
        ensure_ascii=False,
    )
    return AuditResult(
        project_id="",
        audit_version=1,
        type=issue_type,
        severity=getattr(final_issue, "severity", "warning"),
        sheet_no_a=getattr(final_issue, "source_sheet_no", None),
        sheet_no_b=target_sheet_nos[0] if target_sheet_nos else None,
        location=getattr(final_issue, "location_text", None),
        rule_id={
            "missing_ref": "NODE-001",
            "dim_mismatch": "ELEV-001",
            "material_conflict": "MAT-001",
            "index_conflict": "IDX-001",
        }.get(finding_type, "CHIEF-001"),
        finding_type=finding_type,
        finding_status="confirmed",
        source_agent=getattr(final_issue, "source_agent", None),
        evidence_pack_id=getattr(final_issue, "evidence_pack_id", None),
        review_round=getattr(final_issue, "review_round", 1),
        triggered_by=getattr(final_issue, "source_assignment_id", None),
        confidence=getattr(final_issue, "confidence", None),
        description=getattr(final_issue, "description", None),
        evidence_json=evidence_json,
    )


def _persist_final_issues(
    project_id: str,
    audit_version: int,
    final_issues: list,
    *,
    final_review_meta_by_assignment: dict[str, dict] | None = None,
) -> None:  # noqa: ANN001
    if not final_issues:
        return
    rows = []
    for issue in final_issues:
        row = _final_issue_to_audit_result(
            issue,
            final_review_meta_by_assignment=final_review_meta_by_assignment,
        )
        row.project_id = project_id
        row.audit_version = audit_version
        rows.append(row)
    db = SessionLocal()
    try:
        add_and_commit(db, rows)
        append_result_upsert_events(
            project_id,
            audit_version,
            issue_ids=[str(row.id) for row in rows if getattr(row, "id", None)],
        )
    finally:
        db.close()


def _run_relationship_runner(relationship_runner, project_id: str, db, *, audit_version: int, hot_sheet_registry) -> list:  # noqa: ANN001
    try:
        return relationship_runner(
            project_id,
            db,
            audit_version=audit_version,
            hot_sheet_registry=hot_sheet_registry,
        )
    except TypeError:
        return relationship_runner(project_id, db, audit_version=audit_version)


def _invoke_pipeline_impl(func, project_id: str, audit_version: int, **kwargs):  # noqa: ANN001
    try:
        signature = inspect.signature(func)
    except (TypeError, ValueError):
        return func(project_id, audit_version, **kwargs)
    accepts_var_kwargs = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if accepts_var_kwargs:
        return func(project_id, audit_version, **kwargs)
    supported = {
        key: value
        for key, value in kwargs.items()
        if key in signature.parameters
    }
    return func(project_id, audit_version, **supported)


def execute_pipeline(
    project_id: str,
    audit_version: int,
    *,
    allow_incomplete: bool = False,
    clear_running,
    resume_existing: bool = False,
    worker_generation: int | None = None,
    is_current_worker=None,  # noqa: ANN001
) -> None:
    pipeline_mode = resolve_pipeline_mode()
    if pipeline_mode == "chief_review":
        _invoke_pipeline_impl(
            execute_pipeline_chief_review,
            project_id,
            audit_version,
            allow_incomplete=allow_incomplete,
            clear_running=clear_running,
            resume_existing=resume_existing,
            worker_generation=worker_generation,
            is_current_worker=is_current_worker,
        )
        return

    if pipeline_mode == "v2":
        _invoke_pipeline_impl(
            execute_pipeline_v2,
            project_id,
            audit_version,
            allow_incomplete=allow_incomplete,
            clear_running=clear_running,
            resume_existing=resume_existing,
            worker_generation=worker_generation,
            is_current_worker=is_current_worker,
        )
        return

    _invoke_pipeline_impl(
        execute_pipeline_legacy,
        project_id,
        audit_version,
        allow_incomplete=allow_incomplete,
        clear_running=clear_running,
        resume_existing=resume_existing,
        worker_generation=worker_generation,
        is_current_worker=is_current_worker,
    )


def execute_pipeline_chief_review(
    project_id: str,
    audit_version: int,
    *,
    allow_incomplete: bool = False,
    clear_running,
    resume_existing: bool = False,
    worker_generation: int | None = None,
    is_current_worker=None,  # noqa: ANN001
) -> None:
    from services.audit_runtime.chief_review_session import ChiefReviewSession
    from services.audit_runtime.chief_review_planner import plan_chief_review_hypotheses
    from services.audit_runtime.final_issue_converter import convert_markdown_and_evidence_to_final_issues
    from services.audit_runtime.finding_synthesizer import synthesize_findings
    from services.audit_runtime.report_organizer_agent import run_report_organizer_agent
    from services.audit_runtime.review_worker_pool import ReviewWorkerPool
    from services.chief_review_memory_service import load_project_memory, save_project_memory

    chief_budget = VisualBudget(
        image_budget=_read_budget_env("AUDIT_IMAGE_BUDGET", 200_000),
        request_budget=_read_budget_env("AUDIT_REQUEST_BUDGET", 120),
        retry_budget=_read_budget_env("AUDIT_RETRY_BUDGET", 20),
        priority_reserve_budget=_read_budget_env("AUDIT_PRIORITY_RESERVE_BUDGET", 40_000),
    )
    set_active_visual_budget(chief_budget)
    try:
        _raise_if_cancelled(project_id, worker_generation=worker_generation, is_current_worker=is_current_worker)
        _append_master_event(
            project_id,
            audit_version,
            level="info",
            step_key="prepare",
            event_kind="phase_started",
            progress_hint=5,
            message="主审 Agent 正在整理这次审图需要的基础数据",
            meta={"planner": "chief_review_agent"},
        )
        update_run_progress(
            project_id,
            audit_version,
            status="running",
            current_step="主审准备基础数据",
            progress=5,
        )

        db = SessionLocal()
        try:
            match_result = match_three_lines(project_id, db)
            summary = match_result["summary"]
            if summary["total"] == 0:
                raise RuntimeError(
                    "三线匹配未完成："
                    f"总数{summary['total']}，就绪{summary['ready']}，"
                    f"缺PNG{summary['missing_png']}，缺JSON{summary['missing_json']}，"
                    f"都缺{summary['missing_all']}"
                )
            if summary["ready"] != summary["total"] and not allow_incomplete:
                raise RuntimeError(
                    "三线匹配未完成："
                    f"总数{summary['total']}，就绪{summary['ready']}，"
                    f"缺PNG{summary['missing_png']}，缺JSON{summary['missing_json']}，"
                    f"都缺{summary['missing_all']}"
                )
            _append_master_event(
                project_id,
                audit_version,
                level="success",
                step_key="prepare",
                event_kind="phase_completed",
                progress_hint=8,
                message=f"主审 Agent 已整理好基础数据，共 {summary['ready']} 张图纸可进入审图",
                meta={"ready": summary["ready"], "total": summary["total"]},
            )
        finally:
            db.close()

        update_run_progress(
            project_id,
            audit_version,
            current_step="主审整理图纸上下文",
            progress=10,
        )
        db = SessionLocal()
        try:
            context_summary = build_sheet_contexts(project_id, db)
            ready_count = int((context_summary or {}).get("ready_contexts", (context_summary or {}).get("ready", 0)))
            _append_master_event(
                project_id,
                audit_version,
                level="success",
                step_key="context",
                event_kind="phase_completed",
                progress_hint=12,
                message=f"主审 Agent 已整理好图纸上下文，当前有 {ready_count} 张图纸可继续分析",
                meta=context_summary if isinstance(context_summary, dict) else None,
            )

            contexts = db.query(SheetContext).filter(SheetContext.project_id == project_id).all()
            edges = db.query(SheetEdge).filter(SheetEdge.project_id == project_id).all()
            sheet_graph = _build_chief_sheet_graph(
                project_id=project_id,
                audit_version=audit_version,
                sheet_contexts=contexts,
                sheet_edges=edges,
            )
            memory = load_project_memory(
                db,
                project_id=project_id,
                audit_version=audit_version,
            )
            memory = save_project_memory(
                db,
                project_id=project_id,
                audit_version=audit_version,
                payload={
                    **memory,
                    "sheet_graph_version": f"chief-review-{audit_version}",
                    "sheet_graph_semantics_source": "chief_llm_runner",
                    "sheet_summaries": [
                        {
                            "sheet_no": ctx.sheet_no,
                            "sheet_name": ctx.sheet_name,
                            "sheet_type": sheet_graph.sheet_types.get(ctx.sheet_no or "", "unknown"),
                        }
                        for ctx in contexts
                    ],
                    "confirmed_links": [
                        {"source_sheet_no": source, "target_sheet_nos": list(targets)}
                        for source, targets in sheet_graph.linked_targets.items()
                    ],
                },
            )
            planner_result = plan_chief_review_hypotheses(
                project_id=project_id,
                audit_version=audit_version,
                memory=memory,
                sheet_graph=sheet_graph,
            )
            memory = save_project_memory(
                db,
                project_id=project_id,
                audit_version=audit_version,
                payload={
                    **memory,
                    "active_hypotheses": planner_result.items,
                    "chief_recheck_queue": planner_result.chief_recheck_queue,
                    "chief_planner_meta": planner_result.meta,
                },
            )
            _append_master_event(
                project_id,
                audit_version,
                level="info",
                step_key="chief_prompt",
                event_kind="phase_completed",
                progress_hint=16,
                message=f"主审 Agent 已装配本轮审图资源，生成 {len(planner_result.items)} 条待核对怀疑卡",
                meta={
                    **planner_result.meta,
                    "chief_recheck_count": len(planner_result.chief_recheck_queue),
                },
            )
        finally:
            db.close()

        update_run_progress(
            project_id,
            audit_version,
            current_step="主审派发副审任务",
            progress=18,
        )
        chief_session = ChiefReviewSession(project_id=project_id, audit_version=audit_version)
        assignments = chief_session.plan_assignments(memory=memory)
        db = SessionLocal()
        try:
            memory = save_project_memory(
                db,
                project_id=project_id,
                audit_version=audit_version,
                payload={
                    **memory,
                    "pending_assignments": [item.model_dump() for item in assignments],
                    "completed_assignment_ids": [],
                    "chief_dispatch_meta": {
                        "planned_assignment_count": len(assignments),
                        "dispatch_mode": "incremental_assignment",
                    },
                },
            )
        finally:
            db.close()
        _append_master_event(
            project_id,
            audit_version,
            level="info",
            step_key="chief_planning",
            event_kind="phase_completed",
            progress_hint=20,
            message=f"主审 Agent 已生成 {len(assignments)} 张副审任务卡",
            meta={
                "planner": "chief_review_agent",
                "planner_source": planner_result.meta.get("planner_source"),
                "review_assignments": len(assignments),
                "worker_tasks": len(assignments),
                "chief_recheck_count": len(planner_result.chief_recheck_queue),
                "task_stage": "worker_task_planning",
            },
        )

        worker_results = []
        chief_approved_issue_candidates: list[dict] = []
        chief_recheck_records: list[dict] = []
        chief_rejected_records: list[dict] = []
        chief_review_decisions: list[dict] = []
        accepted_worker_results: list = []
        final_review_escalations: list[dict] = []
        final_review_decisions: list[dict] = []
        redispatch_assignments: list = []

        def _handle_worker_result_incrementally(*, assignment, worker_task, worker_result):  # noqa: ANN001
            single_approved, single_recheck, single_rejected, single_decisions = (
                _route_worker_results_back_to_chief_review(
                    assignments=assignments,
                    worker_results=[worker_result],
                )
            )
            chief_approved_issue_candidates.extend(single_approved)
            chief_recheck_records.extend(single_recheck)
            chief_rejected_records.extend(single_rejected)
            chief_review_decisions.extend(single_decisions)

            latest_decision = single_decisions[0] if single_decisions else {}
            assignment_id = str(latest_decision.get("assignment_id") or getattr(assignment, "assignment_id", "") or "").strip()
            chief_decision = str(latest_decision.get("chief_decision") or "recheck").strip()
            processed_count = len(chief_review_decisions)
            total_count = max(len(assignments), 1)
            progress_hint = min(88, 60 + int((processed_count / total_count) * 28))
            _append_master_event(
                project_id,
                audit_version,
                level="info",
                step_key="chief_review",
                event_kind="phase_progress",
                progress_hint=progress_hint,
                message=(
                    f"主审 Agent 已收回副审任务 {processed_count}/{len(assignments)}："
                    f"{assignment_id or getattr(worker_task, 'id', 'unknown-assignment')}（{chief_decision}）"
                ),
                meta={
                    "assignment_id": assignment_id or getattr(worker_task, "id", None),
                    "chief_decision": chief_decision,
                    "chief_rationale": str(latest_decision.get("chief_rationale") or "").strip() or None,
                    "task_stage": "chief_recheck",
                },
            )
            update_run_progress(
                project_id,
                audit_version,
                current_step="主审复核副审分歧",
                progress=progress_hint,
            )

            if not single_approved:
                return

            accepted, escalations, decisions, redispatches = _route_worker_results_through_final_review(
                chief_review_records=single_approved,
                project_id=project_id,
                audit_version=audit_version,
                chief_session=chief_session,
                memory=memory,
            )
            accepted_worker_results.extend(accepted)
            final_review_escalations.extend(escalations)
            final_review_decisions.extend(decisions)
            redispatch_assignments.extend(redispatches)

        if assignments:
            worker_results = asyncio.run(
                _dispatch_review_assignments_incrementally(
                    chief_session=chief_session,
                    assignments=assignments,
                    on_assignment_completed=_handle_worker_result_incrementally,
                )
            ) or []
        final_review_source_counts: dict[str, int] = defaultdict(int)
        for item in final_review_decisions:
            source = str(
                getattr(item.get("final_review_decision"), "decision_source", "") or ""
            ).strip() or "rule_fallback"
            final_review_source_counts[source] += 1
        accepted_decision_records = [
            item
            for item in final_review_decisions
            if str(getattr(item.get("final_review_decision"), "decision", "") or "").strip() == "accepted"
        ]
        final_review_meta_by_assignment = {
            str(item.get("assignment_id") or "").strip(): {
                "decision": str(getattr(item.get("final_review_decision"), "decision", "") or "").strip(),
                "decision_source": str(
                    getattr(item.get("final_review_decision"), "decision_source", "") or ""
                ).strip() or "rule_fallback",
                "rationale": str(getattr(item.get("final_review_decision"), "rationale", "") or "").strip(),
                "requires_grounding": bool(
                    getattr(item.get("final_review_decision"), "requires_grounding", True)
                ),
            }
            for item in final_review_decisions
            if str(item.get("assignment_id") or "").strip()
        }
        handled_assignment_ids = {
            str(item.get("assignment_id") or "").strip()
            for item in accepted_decision_records
            if str(item.get("assignment_id") or "").strip()
        }
        compatibility_worker_results = [
            item
            for item in accepted_worker_results
            if str(
                (item.meta or {}).get("assignment_id")
                or (item.evidence_bundle or {}).get("assignment_id")
                or item.task_id
                or ""
            ).strip()
            not in handled_assignment_ids
        ]

        organizer_markdown = ""
        final_issues = []
        if accepted_decision_records:
            organizer_markdown = run_report_organizer_agent(
                accepted_decisions=accepted_decision_records,
            )
            final_issues = convert_markdown_and_evidence_to_final_issues(
                organizer_markdown=organizer_markdown,
                accepted_decisions=accepted_decision_records,
            )

        findings, worker_escalations = synthesize_findings(worker_results=compatibility_worker_results)
        chief_review_escalations = [
            {
                "hypothesis_id": item["worker_result"].hypothesis_id,
                "task_id": item["worker_result"].task_id,
                "assignment_id": item["assignment_id"],
                "escalate_to_chief": True,
                "reasons": ["chief_recheck"],
                "rationale": str(item.get("chief_rationale") or "").strip() or "主审要求继续复核",
            }
            for item in chief_recheck_records
            if item.get("worker_result") is not None
        ]
        escalations = [*chief_review_escalations, *final_review_escalations, *worker_escalations]
        resolved_refs = [
            SimpleNamespace(triggered_by=str(item["worker_result"].hypothesis_id or "").strip())
            for item in accepted_decision_records
            if str(item["worker_result"].hypothesis_id or "").strip()
        ]
        db = SessionLocal()
        try:
            memory = save_project_memory(
                db,
                project_id=project_id,
                audit_version=audit_version,
                payload=_update_chief_review_memory(
                    {
                        **memory,
                        "pending_assignments": [],
                        "completed_assignment_ids": [item.assignment_id for item in assignments],
                        "chief_dispatch_meta": {
                            **dict(memory.get("chief_dispatch_meta") or {}),
                            "completed_assignment_count": len(worker_results),
                            "chief_review_decision_count": len(chief_review_decisions),
                            "chief_review_recheck_count": len(chief_recheck_records),
                            "chief_review_rejected_count": len(chief_rejected_records),
                            "final_review_decision_count": len(final_review_decisions),
                            "final_review_llm_decision_count": int(final_review_source_counts.get("llm", 0)),
                            "final_review_rule_fallback_count": int(
                                final_review_source_counts.get("rule_fallback", 0)
                            ),
                            "redispatch_assignment_count": len(redispatch_assignments),
                            "accepted_final_issue_count": len(final_issues),
                        },
                    },
                    worker_results=worker_results,
                    findings=[*findings, *resolved_refs],
                    escalations=escalations,
                ),
            )
        finally:
            db.close()
        _persist_final_issues(
            project_id,
            audit_version,
            final_issues,
            final_review_meta_by_assignment=final_review_meta_by_assignment,
        )
        _persist_chief_findings(project_id, audit_version, findings)

        if escalations:
            _append_master_event(
                project_id,
                audit_version,
                level="warning",
                step_key="chief_review",
                event_kind="warning",
                progress_hint=92,
                message=f"主审 Agent 发现 {len(escalations)} 组副审结果冲突，已升级回主审待复核",
                meta={
                    "escalations": escalations[:10],
                    "task_stage": "chief_recheck",
                    "redispatch_assignments": len(redispatch_assignments),
                },
            )

        update_run_progress(
            project_id,
            audit_version,
            status="done",
            current_step="主审完成结果收束",
            progress=100,
            total_issues=len(final_issues) + len(findings),
            finished=True,
        )
        _append_master_event(
            project_id,
            audit_version,
            step_key="done",
            level="success",
            event_kind="phase_completed",
            progress_hint=100,
            message=f"主审 Agent 已整理完成审核报告，共汇总 {len(final_issues) + len(findings)} 处问题",
            meta={
                "planner": "chief_review_agent",
                "total_issues": len(final_issues) + len(findings),
                "final_issues": len(final_issues),
                "compat_findings": len(findings),
                "organizer_markdown_length": len(organizer_markdown),
                "escalations": len(escalations),
                "task_stage": "organizer_converted",
            },
        )
        append_result_summary_event(project_id, audit_version)
        set_project_status(project_id, "done")

        db = SessionLocal()
        try:
            increment_cache_version(project_id, db)
        finally:
            db.close()
    except AuditSupersededError as exc:
        _append_master_event(
            project_id,
            audit_version,
            step_key="handoff",
            level="warning",
            event_kind="master_handoff",
            progress_hint=0,
            message="主审 Agent 已把现场交给新的恢复线程，当前线程准备退出",
            meta={"reason": str(exc), "planner": "chief_review_agent"},
        )
    except (AuditCancelledError, AuditCancellationRequested) as exc:
        mark_running_tasks_failed(project_id, audit_version, "cancelled_by_user")
        db = SessionLocal()
        try:
            (
                db.query(AuditResult)
                .filter(
                    AuditResult.project_id == project_id,
                    AuditResult.audit_version == audit_version,
                )
                .delete(synchronize_session=False)
            )
            db.commit()
        finally:
            db.close()
        update_run_progress(
            project_id,
            audit_version,
            status="failed",
            current_step="主审流程已中断",
            error=str(exc),
            finished=True,
        )
        _append_master_event(
            project_id,
            audit_version,
            step_key="cancelled",
            level="warning",
            event_kind="warning",
            progress_hint=100,
            message="主审 Agent 已停止本次审图，后台任务已经结束",
            meta={"error": str(exc), "planner": "chief_review_agent"},
        )
        append_result_summary_event(project_id, audit_version)
        set_project_status(project_id, "ready")
    except Exception as exc:  # noqa: BLE001
        mark_running_tasks_failed(project_id, audit_version, f"chief_review_failed:{str(exc)}")
        update_run_progress(
            project_id,
            audit_version,
            status="failed",
            current_step="主审流程失败",
            error=str(exc),
            finished=True,
        )
        _append_master_event(
            project_id,
            audit_version,
            step_key="failed",
            level="error",
            event_kind="error",
            progress_hint=100,
            message="主审 Agent 在整理本次审图时遇到问题，任务已停止",
            meta={"error": str(exc), "planner": "chief_review_agent"},
        )
        append_result_summary_event(project_id, audit_version)
        set_project_status(project_id, "ready")
    finally:
        set_active_visual_budget(None)
        clear_cancel_request(project_id)
        clear_running(project_id)


def execute_pipeline_v2(
    project_id: str,
    audit_version: int,
    *,
    allow_incomplete: bool = False,
    clear_running,
    resume_existing: bool = False,
    worker_generation: int | None = None,
    is_current_worker=None,  # noqa: ANN001
) -> None:
    v2_policy = build_default_evidence_policy()
    budget = VisualBudget(
        image_budget=_read_budget_env("AUDIT_IMAGE_BUDGET", 200_000),
        request_budget=_read_budget_env("AUDIT_REQUEST_BUDGET", 120),
        retry_budget=_read_budget_env("AUDIT_RETRY_BUDGET", 20),
        priority_reserve_budget=_read_budget_env("AUDIT_PRIORITY_RESERVE_BUDGET", 40_000),
    )
    logger.info(
        "project=%s audit_version=%s orchestrator=v2 bootstrap->legacy policy=%s budget=%s",
        project_id,
        audit_version,
        sorted(v2_policy.keys()),
        budget.snapshot(),
    )
    _append_master_event(
        project_id,
        audit_version,
        level="info",
        step_key="prepare",
        event_kind="phase_progress",
        progress_hint=4,
        message="总控规划Agent 已初始化本轮视觉预算，后续证据申请会按预算自动降级或保留重点额度",
        meta=budget.snapshot(),
    )
    hot_sheet_registry = HotSheetRegistry()
    set_active_visual_budget(budget)
    try:
        execute_pipeline_legacy(
            project_id,
            audit_version,
            allow_incomplete=allow_incomplete,
            clear_running=clear_running,
            relationship_runner=discover_relationships_v2,
            hot_sheet_registry=hot_sheet_registry,
            visual_budget=budget,
            resume_existing=resume_existing,
            worker_generation=worker_generation,
            is_current_worker=is_current_worker,
        )
    finally:
        set_active_visual_budget(None)


def execute_pipeline_legacy(
    project_id: str,
    audit_version: int,
    *,
    allow_incomplete: bool = False,
    clear_running,
    relationship_runner=discover_relationships,
    hot_sheet_registry: HotSheetRegistry | None = None,
    visual_budget: VisualBudget | None = None,
    resume_existing: bool = False,
    worker_generation: int | None = None,
    is_current_worker=None,  # noqa: ANN001
) -> None:  # noqa: ANN001
    """后台线程执行审核流程（按 audit_tasks 驱动）。"""
    try:
        _raise_if_cancelled(project_id, worker_generation=worker_generation, is_current_worker=is_current_worker)
        _append_master_event(
            project_id,
            audit_version,
            level="info",
            step_key="prepare",
            event_kind="phase_started",
            progress_hint=5,
            message="总控规划Agent 正在整理这次审图需要的基础数据",
        )
        update_run_progress(
            project_id,
            audit_version,
            status="running",
            current_step="校验三线匹配",
            progress=5,
        )

        _raise_if_cancelled(project_id, worker_generation=worker_generation, is_current_worker=is_current_worker)
        db = SessionLocal()
        try:
            match_result = match_three_lines(project_id, db)
            summary = match_result["summary"]
            if summary["total"] == 0:
                raise RuntimeError(
                    "三线匹配未完成："
                    f"总数{summary['total']}，就绪{summary['ready']}，"
                    f"缺PNG{summary['missing_png']}，缺JSON{summary['missing_json']}，"
                    f"都缺{summary['missing_all']}"
                )
            if summary["ready"] != summary["total"] and not allow_incomplete:
                raise RuntimeError(
                    "三线匹配未完成："
                    f"总数{summary['total']}，就绪{summary['ready']}，"
                    f"缺PNG{summary['missing_png']}，缺JSON{summary['missing_json']}，"
                    f"都缺{summary['missing_all']}"
                )
            if summary["ready"] != summary["total"] and allow_incomplete:
                logger.warning(
                    "project=%s audit_version=%s starting with incomplete three-line match: "
                    "total=%s ready=%s missing_png=%s missing_json=%s missing_all=%s",
                    project_id, audit_version,
                    summary["total"], summary["ready"],
                    summary["missing_png"], summary["missing_json"], summary["missing_all"],
                )
            _append_master_event(
                project_id,
                audit_version,
                level="success",
                step_key="prepare",
                event_kind="phase_completed",
                progress_hint=8,
                message=f"总控规划Agent 已整理好基础数据，共 {summary['ready']} 张图纸可进入审图",
                meta={"ready": summary["ready"], "total": summary["total"]},
            )
        finally:
            db.close()

        update_run_progress(
            project_id,
            audit_version,
            current_step="构建图纸上下文",
            progress=10,
        )
        _append_master_event(
            project_id,
            audit_version,
            level="info",
            step_key="context",
            event_kind="phase_progress",
            progress_hint=10,
            message="总控规划Agent 正在整理图纸上下文，准备分配后续审核任务",
        )
        _raise_if_cancelled(project_id, worker_generation=worker_generation, is_current_worker=is_current_worker)
        db = SessionLocal()
        try:
            context_summary = build_sheet_contexts(project_id, db)
            summary = context_summary or {}
            ready_count = int(summary.get("ready_contexts", summary.get("ready", 0)))
            _append_master_event(
                project_id,
                audit_version,
                level="success",
                step_key="context",
                event_kind="phase_completed",
                progress_hint=11,
                message=f"总控规划Agent 已整理好图纸上下文，当前有 {ready_count} 张图纸可继续分析",
                meta=context_summary if isinstance(context_summary, dict) else None,
            )
        finally:
            db.close()

        update_run_progress(
            project_id,
            audit_version,
            current_step="AI 分析图纸关系",
            progress=12,
        )
        existing_tasks = load_tasks(project_id, audit_version) if resume_existing else []
        if existing_tasks:
            _append_master_event(
                project_id,
                audit_version,
                level="info",
                step_key="task_planning",
                event_kind="master_resume_requested",
                progress_hint=18,
                message="总控规划Agent 正在从任务账本恢复现场，不再从零重新派工",
                meta={"existing_tasks": len(existing_tasks), "resume_existing": True},
            )
            update_run_progress(
                project_id,
                audit_version,
                current_step="从任务账本恢复总控现场",
                progress=18,
            )
            all_tasks = existing_tasks
        else:
            _append_worker_event(
                project_id,
                audit_version,
                step_key="relationship_discovery",
                agent_key="relationship_review_agent",
                agent_name="关系审查Agent",
                level="info",
                event_kind="phase_started",
                progress_hint=12,
                message="关系审查Agent 开始分析跨图关系，正在找出值得继续核对的图纸关联",
            )
            _raise_if_cancelled(project_id, worker_generation=worker_generation, is_current_worker=is_current_worker)
            db = SessionLocal()
            try:
                ai_relationships = _run_relationship_runner(
                    relationship_runner,
                    project_id,
                    db,
                    audit_version=audit_version,
                    hot_sheet_registry=hot_sheet_registry,
                )
                ai_edges_count = save_ai_edges(project_id, ai_relationships, db)
                _append_worker_event(
                    project_id,
                    audit_version,
                    step_key="relationship_discovery",
                    agent_key="relationship_review_agent",
                    agent_name="关系审查Agent",
                    level="success",
                    event_kind="phase_completed",
                    progress_hint=16,
                    message=f"关系审查Agent 已完成首轮关系分析，整理出 {ai_edges_count} 处可继续审核的关联",
                    meta={
                        "discovered": ai_edges_count,
                        "budget_usage": visual_budget.snapshot() if visual_budget else None,
                        "hot_sheets": [item.sheet_no for item in hot_sheet_registry.get_hot_sheets()[:5]] if hot_sheet_registry else [],
                    },
                )
                logger.info(
                    "project=%s audit_version=%s ai_relationship_discovery edges=%s",
                    project_id, audit_version, ai_edges_count,
                )
            except AuditCancellationRequested as exc:
                raise AuditCancelledError(str(exc)) from exc
            except Exception as exc:
                _append_worker_event(
                    project_id,
                    audit_version,
                    step_key="relationship_discovery",
                    agent_key="relationship_review_agent",
                    agent_name="关系审查Agent",
                    level="warning",
                    event_kind="warning",
                    progress_hint=16,
                    message="关系审查Agent 暂时没有拿到完整关系结果，系统会继续后续审核并保留已得到的信息",
                    meta={"error": str(exc)},
                )
                logger.warning(
                    "project=%s AI关系发现降级: %s", project_id, exc,
                )
            finally:
                db.close()

            update_run_progress(
                project_id,
                audit_version,
                current_step="规划审核任务图",
                progress=18,
            )
            _append_master_event(
                project_id,
                audit_version,
                level="info",
                step_key="task_planning",
                event_kind="phase_started",
                progress_hint=18,
                message="总控规划Agent 正在生成审核任务图，准备进入深度检查",
            )
            _raise_if_cancelled(project_id, worker_generation=worker_generation, is_current_worker=is_current_worker)
            db = SessionLocal()
            try:
                task_summary = build_audit_tasks(project_id, audit_version, db)
                total_planned = int((task_summary or {}).get("total_tasks", 0))
                _append_master_event(
                    project_id,
                    audit_version,
                    level="success",
                    step_key="task_planning",
                    event_kind="phase_completed",
                    progress_hint=20,
                    message=f"总控规划Agent 已生成审核任务图，共安排 {total_planned} 项检查",
                    meta=task_summary if isinstance(task_summary, dict) else None,
                )
            finally:
                db.close()

            all_tasks = load_tasks(project_id, audit_version)
        if not all_tasks:
            _append_master_event(
                project_id,
                audit_version,
                level="warning",
                step_key="task_planning",
                event_kind="warning",
                progress_hint=20,
                message="总控规划Agent 暂时没有规划出可执行任务，请先检查图纸数据是否完整",
            )
            raise RuntimeError("审核任务图为空，请先检查图纸上下文构建结果。")

        total_tasks = len(all_tasks)
        completed_tasks = len(
            [
                task
                for task in all_tasks
                if str(task.status or "").strip() == "done" or str(task.result_ref or "").strip() == "permanently_failed"
            ]
        )
        total_issues = 0
        isolated_failures = 0

        index_tasks = [
            task for task in all_tasks
            if task.task_type == "index"
            and str(task.status or "").strip() != "done"
            and str(task.result_ref or "").strip() != "permanently_failed"
        ]
        dimension_tasks = [
            task for task in all_tasks
            if task.task_type == "dimension"
            and str(task.status or "").strip() != "done"
            and str(task.result_ref or "").strip() != "permanently_failed"
        ]
        material_tasks = [
            task for task in all_tasks
            if task.task_type == "material"
            and str(task.status or "").strip() != "done"
            and str(task.result_ref or "").strip() != "permanently_failed"
        ]
        logger.info(
            "project=%s audit_version=%s tasks total=%s index=%s dimension=%s material=%s",
            project_id,
            audit_version,
            total_tasks,
            len(index_tasks),
            len(dimension_tasks),
            len(material_tasks),
        )

        if index_tasks:
            _raise_if_cancelled(project_id, worker_generation=worker_generation, is_current_worker=is_current_worker)
            _append_worker_event(
                project_id,
                audit_version,
                step_key="index",
                agent_key="index_review_agent",
                agent_name="索引审查Agent",
                level="info",
                event_kind="phase_started",
                progress_hint=progress_by_task(completed_tasks, total_tasks),
                message=f"索引审查Agent 开始核对索引关系，共有 {len(index_tasks)} 项检查待处理",
            )
            update_run_progress(
                project_id,
                audit_version,
                current_step=f"索引核对（{len(index_tasks)}任务）",
                progress=progress_by_task(completed_tasks, total_tasks),
                total_issues=total_issues,
            )
            set_task_status_batch(
                project_id,
                audit_version,
                [task.id for task in index_tasks],
                "running",
                note="index_audit_started",
            )
            index_stage_succeeded = True
            try:
                db = SessionLocal()
                try:
                    index_issues = audit_indexes(
                        project_id,
                        audit_version,
                        db,
                        source_sheet_filters=task_group_source_sheets(index_tasks),
                        hot_sheet_registry=hot_sheet_registry,
                    )
                finally:
                    db.close()
            except Exception as exc:
                index_issues, index_stage_succeeded = _recover_stage_once(
                    project_id,
                    audit_version,
                    step_key="index",
                    agent_key="index_review_agent",
                    agent_name="索引审查Agent",
                    tasks=index_tasks,
                    run_stage=lambda: _run_with_session(
                        lambda db: audit_indexes(
                            project_id,
                            audit_version,
                            db,
                            source_sheet_filters=task_group_source_sheets(index_tasks),
                            hot_sheet_registry=hot_sheet_registry,
                        )
                    ),
                    progress_hint=progress_by_task(completed_tasks, total_tasks),
                    task_type="index",
                    exc=exc,
                )
                if not index_stage_succeeded:
                    isolated_failures += 1
                    _isolate_stage_failure(
                        project_id,
                        audit_version,
                        step_key="index",
                        agent_key="index_review_agent",
                        agent_name="索引审查Agent",
                        task_ids=[task.id for task in index_tasks],
                        progress_hint=progress_by_task(completed_tasks, total_tasks),
                        note="index_audit_failed",
                        exc=exc,
                    )
                    update_run_progress(
                        project_id,
                        audit_version,
                        current_step="索引核对局部失败，继续后续检查",
                        progress=progress_by_task(completed_tasks, total_tasks),
                        total_issues=total_issues,
                    )

            _raise_if_cancelled(project_id, worker_generation=worker_generation, is_current_worker=is_current_worker)
            if index_stage_succeeded:
                total_issues += len(index_issues)
                completed_tasks += len(index_tasks)
                _append_worker_event(
                    project_id,
                    audit_version,
                    step_key="index",
                    agent_key="index_review_agent",
                    agent_name="索引审查Agent",
                    level="success",
                    event_kind="phase_completed",
                    progress_hint=progress_by_task(completed_tasks, total_tasks),
                    message=f"索引审查Agent 已完成本轮核对，发现 {len(index_issues)} 处需要关注的问题",
                    meta={
                        "issues": len(index_issues),
                        "tasks": len(index_tasks),
                        "budget_usage": visual_budget.snapshot() if visual_budget else None,
                        "hot_sheets": [item.sheet_no for item in hot_sheet_registry.get_hot_sheets()[:5]] if hot_sheet_registry else [],
                    },
                )
                set_task_status_batch(
                    project_id,
                    audit_version,
                    [task.id for task in index_tasks],
                    "done",
                    note=f"index_audit_done issues={len(index_issues)}",
                    result_ref=f"index:{len(index_issues)}",
                )
                update_run_progress(
                    project_id,
                    audit_version,
                    current_step=f"索引核对完成（{len(index_tasks)}/{len(index_tasks)}）",
                    progress=progress_by_task(completed_tasks, total_tasks),
                    total_issues=total_issues,
                )

        if dimension_tasks:
            _raise_if_cancelled(project_id, worker_generation=worker_generation, is_current_worker=is_current_worker)
            pair_filters = task_group_pairs(dimension_tasks)
            _append_worker_event(
                project_id,
                audit_version,
                step_key="dimension",
                agent_key="dimension_review_agent",
                agent_name="尺寸审查Agent",
                level="info",
                event_kind="phase_started",
                progress_hint=progress_by_task(completed_tasks, total_tasks),
                message=f"尺寸审查Agent 开始核对尺寸关系，共有 {len(dimension_tasks)} 项检查待处理",
            )
            update_run_progress(
                project_id,
                audit_version,
                current_step=f"尺寸核对（{len(dimension_tasks)}任务）",
                progress=progress_by_task(completed_tasks, total_tasks),
                total_issues=total_issues,
            )
            set_task_status_batch(
                project_id,
                audit_version,
                [task.id for task in dimension_tasks],
                "running",
                note="dimension_audit_started",
            )

            dimension_stage_succeeded = True
            try:
                db = SessionLocal()
                try:
                    dimension_issues = audit_dimensions(
                        project_id,
                        audit_version,
                        db,
                        pair_filters=pair_filters,
                        hot_sheet_registry=hot_sheet_registry,
                    )
                finally:
                    db.close()
            except Exception as exc:
                dimension_issues, dimension_stage_succeeded = _recover_stage_once(
                    project_id,
                    audit_version,
                    step_key="dimension",
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    tasks=dimension_tasks,
                    run_stage=lambda: _run_with_session(
                        lambda db: audit_dimensions(
                            project_id,
                            audit_version,
                            db,
                            pair_filters=pair_filters,
                            hot_sheet_registry=hot_sheet_registry,
                        )
                    ),
                    progress_hint=progress_by_task(completed_tasks, total_tasks),
                    task_type="dimension",
                    exc=exc,
                )
                if not dimension_stage_succeeded:
                    isolated_failures += 1
                    _isolate_stage_failure(
                        project_id,
                        audit_version,
                        step_key="dimension",
                        agent_key="dimension_review_agent",
                        agent_name="尺寸审查Agent",
                        task_ids=[task.id for task in dimension_tasks],
                        progress_hint=progress_by_task(completed_tasks, total_tasks),
                        note="dimension_audit_failed",
                        exc=exc,
                    )
                    update_run_progress(
                        project_id,
                        audit_version,
                        current_step="尺寸核对局部失败，继续后续检查",
                        progress=progress_by_task(completed_tasks, total_tasks),
                        total_issues=total_issues,
                    )

            _raise_if_cancelled(project_id, worker_generation=worker_generation, is_current_worker=is_current_worker)
            if dimension_stage_succeeded:
                total_issues += len(dimension_issues)
                completed_tasks += len(dimension_tasks)
                _append_worker_event(
                    project_id,
                    audit_version,
                    step_key="dimension",
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    level="success",
                    event_kind="phase_completed",
                    progress_hint=progress_by_task(completed_tasks, total_tasks),
                    message=f"尺寸审查Agent 已完成本轮核对，发现 {len(dimension_issues)} 处需要关注的问题",
                    meta={
                        "issues": len(dimension_issues),
                        "tasks": len(dimension_tasks),
                        "budget_usage": visual_budget.snapshot() if visual_budget else None,
                        "hot_sheets": [item.sheet_no for item in hot_sheet_registry.get_hot_sheets()[:5]] if hot_sheet_registry else [],
                    },
                )
                set_task_status_batch(
                    project_id,
                    audit_version,
                    [task.id for task in dimension_tasks],
                    "done",
                    note=f"dimension_audit_done issues={len(dimension_issues)} pairs={len(pair_filters)}",
                    result_ref=f"dimension:{len(dimension_issues)}",
                )
                update_run_progress(
                    project_id,
                    audit_version,
                    current_step=f"尺寸核对完成（{len(dimension_tasks)}/{len(dimension_tasks)}）",
                    progress=progress_by_task(completed_tasks, total_tasks),
                    total_issues=total_issues,
                )

        if material_tasks:
            _raise_if_cancelled(project_id, worker_generation=worker_generation, is_current_worker=is_current_worker)
            source_filters = task_group_source_sheets(material_tasks)
            _append_worker_event(
                project_id,
                audit_version,
                step_key="material",
                agent_key="material_review_agent",
                agent_name="材料审查Agent",
                level="info",
                event_kind="phase_started",
                progress_hint=progress_by_task(completed_tasks, total_tasks),
                message=f"材料审查Agent 开始核对材料信息，共有 {len(material_tasks)} 项检查待处理",
            )
            update_run_progress(
                project_id,
                audit_version,
                current_step=f"材料核对（{len(material_tasks)}任务）",
                progress=progress_by_task(completed_tasks, total_tasks),
                total_issues=total_issues,
            )
            set_task_status_batch(
                project_id,
                audit_version,
                [task.id for task in material_tasks],
                "running",
                note="material_audit_started",
            )

            material_stage_succeeded = True
            try:
                db = SessionLocal()
                try:
                    material_issues = audit_materials(
                        project_id,
                        audit_version,
                        db,
                        sheet_filters=source_filters,
                        hot_sheet_registry=hot_sheet_registry,
                    )
                finally:
                    db.close()
            except Exception as exc:
                material_issues, material_stage_succeeded = _recover_stage_once(
                    project_id,
                    audit_version,
                    step_key="material",
                    agent_key="material_review_agent",
                    agent_name="材料审查Agent",
                    tasks=material_tasks,
                    run_stage=lambda: _run_with_session(
                        lambda db: audit_materials(
                            project_id,
                            audit_version,
                            db,
                            sheet_filters=source_filters,
                            hot_sheet_registry=hot_sheet_registry,
                        )
                    ),
                    progress_hint=progress_by_task(completed_tasks, total_tasks),
                    task_type="material",
                    exc=exc,
                )
                if not material_stage_succeeded:
                    isolated_failures += 1
                    _isolate_stage_failure(
                        project_id,
                        audit_version,
                        step_key="material",
                        agent_key="material_review_agent",
                        agent_name="材料审查Agent",
                        task_ids=[task.id for task in material_tasks],
                        progress_hint=progress_by_task(completed_tasks, total_tasks),
                        note="material_audit_failed",
                        exc=exc,
                    )
                    update_run_progress(
                        project_id,
                        audit_version,
                        current_step="材料核对局部失败，本轮继续收尾",
                        progress=progress_by_task(completed_tasks, total_tasks),
                        total_issues=total_issues,
                    )

            _raise_if_cancelled(project_id, worker_generation=worker_generation, is_current_worker=is_current_worker)
            if material_stage_succeeded:
                total_issues += len(material_issues)
                completed_tasks += len(material_tasks)
                _append_worker_event(
                    project_id,
                    audit_version,
                    step_key="material",
                    agent_key="material_review_agent",
                    agent_name="材料审查Agent",
                    level="success",
                    event_kind="phase_completed",
                    progress_hint=progress_by_task(completed_tasks, total_tasks),
                    message=f"材料审查Agent 已完成本轮核对，发现 {len(material_issues)} 处需要关注的问题",
                    meta={
                        "issues": len(material_issues),
                        "tasks": len(material_tasks),
                        "budget_usage": visual_budget.snapshot() if visual_budget else None,
                        "hot_sheets": [item.sheet_no for item in hot_sheet_registry.get_hot_sheets()[:5]] if hot_sheet_registry else [],
                    },
                )
                set_task_status_batch(
                    project_id,
                    audit_version,
                    [task.id for task in material_tasks],
                    "done",
                    note=f"material_audit_done issues={len(material_issues)} sheets={len(source_filters)}",
                    result_ref=f"material:{len(material_issues)}",
                )
                update_run_progress(
                    project_id,
                    audit_version,
                    current_step=f"材料核对完成（{len(material_tasks)}/{len(material_tasks)}）",
                    progress=progress_by_task(completed_tasks, total_tasks),
                    total_issues=total_issues,
                )

        _raise_if_cancelled(project_id, worker_generation=worker_generation, is_current_worker=is_current_worker)
        update_run_progress(
            project_id,
            audit_version,
            status="done",
            current_step="审核完成",
            progress=100,
            total_issues=total_issues,
            finished=True,
        )
        _append_master_event(
            project_id,
            audit_version,
            step_key="done",
            level="success",
            event_kind="phase_completed",
            progress_hint=100,
            message=f"总控规划Agent 已整理完成审核报告，共汇总 {total_issues} 处问题",
            meta={"total_issues": total_issues, "isolated_failures": isolated_failures},
        )
        append_result_summary_event(project_id, audit_version)
        if isolated_failures:
            _append_master_event(
                project_id,
                audit_version,
                step_key="done",
                level="warning",
                event_kind="warning",
                progress_hint=100,
                message=f"总控规划Agent 已隔离 {isolated_failures} 处局部故障，整轮没有被直接打断",
                meta={"isolated_failures": isolated_failures},
            )
        set_project_status(project_id, "done")

        db = SessionLocal()
        try:
            increment_cache_version(project_id, db)
        finally:
            db.close()
    except AuditSupersededError as exc:
        _append_master_event(
            project_id,
            audit_version,
            step_key="handoff",
            level="warning",
            event_kind="master_handoff",
            progress_hint=0,
            message="总控规划Agent 已把现场交给新的恢复线程，当前线程准备退出",
            meta={"reason": str(exc)},
        )
    except (AuditCancelledError, AuditCancellationRequested) as exc:
        mark_running_tasks_failed(project_id, audit_version, "cancelled_by_user")
        db = SessionLocal()
        try:
            (
                db.query(AuditResult)
                .filter(
                    AuditResult.project_id == project_id,
                    AuditResult.audit_version == audit_version,
                )
                .delete(synchronize_session=False)
            )
            db.commit()
        finally:
            db.close()
        update_run_progress(
            project_id,
            audit_version,
            status="failed",
            current_step="审核已中断",
            error=str(exc),
            finished=True,
        )
        _append_master_event(
            project_id,
            audit_version,
            step_key="cancelled",
            level="warning",
            event_kind="warning",
            progress_hint=100,
            message="总控规划Agent 已停止本次审图，后台任务已经结束",
            meta={"error": str(exc)},
        )
        append_result_summary_event(project_id, audit_version)
        set_project_status(project_id, "ready")
    except Exception as exc:  # noqa: BLE001
        mark_running_tasks_failed(project_id, audit_version, f"pipeline_failed:{str(exc)}")
        update_run_progress(
            project_id,
            audit_version,
            status="failed",
            current_step="执行失败",
            error=str(exc),
            finished=True,
        )
        _append_master_event(
            project_id,
            audit_version,
            step_key="failed",
            level="error",
            event_kind="error",
            progress_hint=100,
            message="总控规划Agent 在整理本次审图时遇到问题，任务已停止",
            meta={"error": str(exc)},
        )
        append_result_summary_event(project_id, audit_version)
        set_project_status(project_id, "ready")
    finally:
        clear_cancel_request(project_id)
        clear_running(project_id)
