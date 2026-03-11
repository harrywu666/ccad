"""审计任务编排器。"""

from __future__ import annotations

import logging
import os
from dataclasses import replace
import inspect

from database import SessionLocal
from models import AuditResult, SheetContext, SheetEdge
from services.audit_runtime.cancel_registry import (
    AuditCancellationRequested,
    clear_cancel_request,
    is_cancel_requested,
)
from services.audit import audit_dimensions, audit_indexes, audit_materials
from services.audit_service import match_three_lines
from services.audit_runtime.evidence_planner import build_default_evidence_policy
from services.audit_runtime.finding_schema import apply_finding_to_audit_result
from services.audit_runtime.hot_sheet_registry import HotSheetRegistry
from services.audit_runtime.visual_budget import VisualBudget, set_active_visual_budget
from services.audit_runtime.state_transitions import (
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
    append_run_event(
        project_id,
        audit_version,
        level=level,
        step_key=step_key,
        agent_key="master_planner_agent",
        agent_name="总控规划Agent",
        event_kind=event_kind,
        progress_hint=progress_hint,
        message=message,
        meta=meta,
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
        meta=meta,
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


def _build_default_hypotheses(sheet_graph) -> list[dict]:  # noqa: ANN001
    hypotheses: list[dict] = []
    for index, (source_sheet_no, target_sheet_nos) in enumerate(sorted(sheet_graph.linked_targets.items())):
        targets = [str(item).strip() for item in list(target_sheet_nos or []) if str(item).strip()]
        if not targets:
            continue
        hypotheses.append(
            {
                "id": f"hyp-{index + 1}",
                "topic": "跨图一致性",
                "objective": f"复核 {source_sheet_no} 与 {', '.join(targets[:3])} 的跨图一致性",
                "source_sheet_no": source_sheet_no,
                "target_sheet_nos": targets,
                "context": {},
            }
        )
    return hypotheses


async def _default_chief_worker_runner(task):  # noqa: ANN001
    from services.audit_runtime.review_task_schema import WorkerResultCard

    return WorkerResultCard(
        task_id=task.id,
        hypothesis_id=task.hypothesis_id,
        worker_kind=task.worker_kind,
        status="rejected",
        confidence=0.35,
        summary=f"{task.worker_kind} worker 模板已接入，但真实核查链路尚未启用",
        meta={
            "sheet_no": task.source_sheet_no,
            "location": task.objective,
            "rule_id": "CHIEF-BOOTSTRAP",
            "evidence_pack_id": "chief_review_pack",
        },
    )


def _persist_chief_findings(
    project_id: str,
    audit_version: int,
    findings: list,  # noqa: ANN001
) -> None:
    if not findings:
        return
    db = SessionLocal()
    try:
        for finding in findings:
            row = AuditResult(
                project_id=project_id,
                audit_version=audit_version,
                type="chief_review",
                severity=finding.severity,
                sheet_no_a=finding.sheet_no,
                location=finding.location,
                description=finding.description,
            )
            apply_finding_to_audit_result(row, finding)
            db.add(row)
        db.commit()
    finally:
        db.close()


def _read_budget_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(0, value)


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
    if _chief_review_enabled():
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

    if _orchestrator_v2_enabled():
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
    from services.audit_runtime.finding_synthesizer import synthesize_findings
    from services.audit_runtime.review_worker_pool import ReviewWorkerPool
    from services.audit_runtime.sheet_graph_builder import build_sheet_graph
    from services.chief_review_memory_service import load_project_memory, save_project_memory

    chief_budget = VisualBudget(
        run_mode="chief_review",
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
            current_step="主审校验三线匹配",
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
            current_step="主审构建图纸上下文",
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

            contexts = (
                db.query(SheetContext)
                .filter(SheetContext.project_id == project_id)
                .all()
            )
            edges = (
                db.query(SheetEdge)
                .filter(SheetEdge.project_id == project_id)
                .all()
            )
            sheet_graph = build_sheet_graph(sheet_contexts=contexts, sheet_edges=edges)
            memory = load_project_memory(
                db,
                project_id=project_id,
                audit_version=audit_version,
            )
            if not memory.get("active_hypotheses"):
                memory = save_project_memory(
                    db,
                    project_id=project_id,
                    audit_version=audit_version,
                    payload={
                        **memory,
                        "sheet_graph_version": f"chief-review-{audit_version}",
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
                        "active_hypotheses": _build_default_hypotheses(sheet_graph),
                    },
                )
        finally:
            db.close()

        update_run_progress(
            project_id,
            audit_version,
            current_step="主审规划副审任务",
            progress=18,
        )
        chief_session = ChiefReviewSession(project_id=project_id, audit_version=audit_version)
        worker_tasks = chief_session.plan_worker_tasks(memory=memory)
        _append_master_event(
            project_id,
            audit_version,
            level="info",
            step_key="chief_planning",
            event_kind="phase_completed",
            progress_hint=20,
            message=f"主审 Agent 已生成 {len(worker_tasks)} 张副审任务卡",
            meta={"planner": "chief_review_agent", "worker_tasks": len(worker_tasks)},
        )

        worker_results = []
        if worker_tasks:
            pool = ReviewWorkerPool(max_concurrency=4, worker_runner=_default_chief_worker_runner)
            worker_results = _run_async(pool.run_batch(worker_tasks)) or []

        findings, escalations = synthesize_findings(worker_results=worker_results)
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
                meta={"escalations": escalations[:10]},
            )

        update_run_progress(
            project_id,
            audit_version,
            status="done",
            current_step="主审汇总完成",
            progress=100,
            total_issues=len(findings),
            finished=True,
        )
        _append_master_event(
            project_id,
            audit_version,
            step_key="done",
            level="success",
            event_kind="phase_completed",
            progress_hint=100,
            message=f"主审 Agent 已整理完成审核报告，共汇总 {len(findings)} 处问题",
            meta={"planner": "chief_review_agent", "total_issues": len(findings), "escalations": len(escalations)},
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
