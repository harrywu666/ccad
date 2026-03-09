"""审计任务编排器。"""

from __future__ import annotations

import logging
import os

from database import SessionLocal
from models import AuditResult
from services.audit_runtime.cancel_registry import clear_cancel_request, is_cancel_requested
from services.audit import audit_dimensions, audit_indexes, audit_materials
from services.audit_service import match_three_lines
from services.audit_runtime.evidence_planner import build_default_evidence_policy
from services.audit_runtime.state_transitions import (
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


def _raise_if_cancelled(project_id: str) -> None:
    if is_cancel_requested(project_id):
        raise AuditCancelledError("用户手动中断审核")


def _orchestrator_v2_enabled() -> bool:
    return str(os.getenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def execute_pipeline(project_id: str, audit_version: int, *, allow_incomplete: bool = False, clear_running) -> None:  # noqa: ANN001
    if _orchestrator_v2_enabled():
        execute_pipeline_v2(
            project_id,
            audit_version,
            allow_incomplete=allow_incomplete,
            clear_running=clear_running,
        )
        return

    execute_pipeline_legacy(
        project_id,
        audit_version,
        allow_incomplete=allow_incomplete,
        clear_running=clear_running,
    )


def execute_pipeline_v2(project_id: str, audit_version: int, *, allow_incomplete: bool = False, clear_running) -> None:  # noqa: ANN001
    v2_policy = build_default_evidence_policy()
    logger.info(
        "project=%s audit_version=%s orchestrator=v2 bootstrap->legacy policy=%s",
        project_id,
        audit_version,
        sorted(v2_policy.keys()),
    )
    execute_pipeline_legacy(
        project_id,
        audit_version,
        allow_incomplete=allow_incomplete,
        clear_running=clear_running,
        relationship_runner=discover_relationships_v2,
    )


def execute_pipeline_legacy(
    project_id: str,
    audit_version: int,
    *,
    allow_incomplete: bool = False,
    clear_running,
    relationship_runner=discover_relationships,
) -> None:  # noqa: ANN001
    """后台线程执行审核流程（按 audit_tasks 驱动）。"""
    try:
        _raise_if_cancelled(project_id)
        append_run_event(
            project_id,
            audit_version,
            level="info",
            step_key="prepare",
            message="开始准备审图数据",
        )
        update_run_progress(
            project_id,
            audit_version,
            status="running",
            current_step="校验三线匹配",
            progress=5,
        )

        _raise_if_cancelled(project_id)
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
            append_run_event(
                project_id,
                audit_version,
                level="success",
                step_key="prepare",
                message=f"图纸信息整理完成，共 {summary['ready']} 张图纸可进入审图",
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
        append_run_event(
            project_id,
            audit_version,
            level="info",
            step_key="context",
            message="正在整理图纸信息，准备后续审图",
        )
        _raise_if_cancelled(project_id)
        db = SessionLocal()
        try:
            context_summary = build_sheet_contexts(project_id, db)
            ready_count = int((context_summary or {}).get("ready", 0))
            append_run_event(
                project_id,
                audit_version,
                level="success",
                step_key="context",
                message=f"图纸上下文整理完成，已有 {ready_count} 张图纸可继续分析",
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
        append_run_event(
            project_id,
            audit_version,
            level="info",
            step_key="relationship_discovery",
            message="开始分析跨图关系",
        )
        _raise_if_cancelled(project_id)
        db = SessionLocal()
        try:
            ai_relationships = relationship_runner(project_id, db, audit_version=audit_version)
            ai_edges_count = save_ai_edges(project_id, ai_relationships, db)
            append_run_event(
                project_id,
                audit_version,
                level="success",
                step_key="relationship_discovery",
                message=f"跨图关系分析完成，已整理 {ai_edges_count} 处可继续审核的关联",
                meta={"discovered": ai_edges_count},
            )
            logger.info(
                "project=%s audit_version=%s ai_relationship_discovery edges=%s",
                project_id, audit_version, ai_edges_count,
            )
        except Exception as exc:
            append_run_event(
                project_id,
                audit_version,
                level="warning",
                step_key="relationship_discovery",
                message="跨图关系分析暂时没有得到完整结果，系统将继续后续审核",
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
        append_run_event(
            project_id,
            audit_version,
            level="info",
            step_key="task_planning",
            message="正在规划审核任务，准备进入深度检查",
        )
        _raise_if_cancelled(project_id)
        db = SessionLocal()
        try:
            task_summary = build_audit_tasks(project_id, audit_version, db)
            total_planned = int((task_summary or {}).get("total_tasks", 0))
            append_run_event(
                project_id,
                audit_version,
                level="success",
                step_key="task_planning",
                message=f"审核任务规划完成，共生成 {total_planned} 项检查",
                meta=task_summary if isinstance(task_summary, dict) else None,
            )
        finally:
            db.close()

        all_tasks = load_tasks(project_id, audit_version)
        if not all_tasks:
            append_run_event(
                project_id,
                audit_version,
                level="warning",
                step_key="task_planning",
                message="未规划出可执行的审核任务，请先检查图纸数据是否齐全",
            )
            raise RuntimeError("审核任务图为空，请先检查图纸上下文构建结果。")

        total_tasks = len(all_tasks)
        completed_tasks = 0
        total_issues = 0

        index_tasks = [task for task in all_tasks if task.task_type == "index"]
        dimension_tasks = [task for task in all_tasks if task.task_type == "dimension"]
        material_tasks = [task for task in all_tasks if task.task_type == "material"]
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
            _raise_if_cancelled(project_id)
            append_run_event(
                project_id,
                audit_version,
                level="info",
                step_key="index",
                message=f"开始核对索引关系，共 {len(index_tasks)} 项检查",
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
            try:
                db = SessionLocal()
                try:
                    index_issues = audit_indexes(
                        project_id,
                        audit_version,
                        db,
                        source_sheet_filters=task_group_source_sheets(index_tasks),
                    )
                finally:
                    db.close()
            except Exception:
                set_task_status_batch(
                    project_id,
                    audit_version,
                    [task.id for task in index_tasks],
                    "failed",
                    note="index_audit_failed",
                )
                raise

            _raise_if_cancelled(project_id)
            total_issues += len(index_issues)
            completed_tasks += len(index_tasks)
            append_run_event(
                project_id,
                audit_version,
                level="success",
                step_key="index",
                message=f"索引关系核对完成，发现 {len(index_issues)} 处需注意的问题",
                meta={"issues": len(index_issues), "tasks": len(index_tasks)},
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
            _raise_if_cancelled(project_id)
            pair_filters = task_group_pairs(dimension_tasks)
            append_run_event(
                project_id,
                audit_version,
                level="info",
                step_key="dimension",
                message=f"开始核对尺寸关系，共 {len(dimension_tasks)} 项检查",
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

            try:
                db = SessionLocal()
                try:
                    dimension_issues = audit_dimensions(
                        project_id,
                        audit_version,
                        db,
                        pair_filters=pair_filters,
                    )
                finally:
                    db.close()
            except Exception:
                set_task_status_batch(
                    project_id,
                    audit_version,
                    [task.id for task in dimension_tasks],
                    "failed",
                    note="dimension_audit_failed",
                )
                raise

            _raise_if_cancelled(project_id)
            total_issues += len(dimension_issues)
            completed_tasks += len(dimension_tasks)
            append_run_event(
                project_id,
                audit_version,
                level="success",
                step_key="dimension",
                message=f"尺寸关系核对完成，发现 {len(dimension_issues)} 处需注意的问题",
                meta={"issues": len(dimension_issues), "tasks": len(dimension_tasks)},
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
            _raise_if_cancelled(project_id)
            source_filters = task_group_source_sheets(material_tasks)
            append_run_event(
                project_id,
                audit_version,
                level="info",
                step_key="material",
                message=f"开始核对材料信息，共 {len(material_tasks)} 项检查",
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

            try:
                db = SessionLocal()
                try:
                    material_issues = audit_materials(
                        project_id,
                        audit_version,
                        db,
                        sheet_filters=source_filters,
                    )
                finally:
                    db.close()
            except Exception:
                set_task_status_batch(
                    project_id,
                    audit_version,
                    [task.id for task in material_tasks],
                    "failed",
                    note="material_audit_failed",
                )
                raise

            _raise_if_cancelled(project_id)
            total_issues += len(material_issues)
            completed_tasks += len(material_tasks)
            append_run_event(
                project_id,
                audit_version,
                level="success",
                step_key="material",
                message=f"材料信息核对完成，发现 {len(material_issues)} 处需注意的问题",
                meta={"issues": len(material_issues), "tasks": len(material_tasks)},
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

        _raise_if_cancelled(project_id)
        update_run_progress(
            project_id,
            audit_version,
            status="done",
            current_step="审核完成",
            progress=100,
            total_issues=total_issues,
            finished=True,
        )
        append_run_event(
            project_id,
            audit_version,
            level="success",
            step_key="done",
            message=f"审核完成，已整理 {total_issues} 处问题到报告中",
            meta={"total_issues": total_issues},
        )
        set_project_status(project_id, "done")

        db = SessionLocal()
        try:
            increment_cache_version(project_id, db)
        finally:
            db.close()
    except AuditCancelledError as exc:
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
        append_run_event(
            project_id,
            audit_version,
            level="warning",
            step_key="cancelled",
            message="本次审图已停止，系统已结束后台任务",
            meta={"error": str(exc)},
        )
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
        append_run_event(
            project_id,
            audit_version,
            level="error",
            step_key="failed",
            message="审图过程中遇到问题，已停止本次任务",
            meta={"error": str(exc)},
        )
        set_project_status(project_id, "ready")
    finally:
        clear_cancel_request(project_id)
        clear_running(project_id)
