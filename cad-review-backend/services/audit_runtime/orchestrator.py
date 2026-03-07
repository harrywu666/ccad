"""审计任务编排器。"""

from __future__ import annotations

import logging

from database import SessionLocal
from models import AuditResult
from services.audit_runtime.cancel_registry import clear_cancel_request, is_cancel_requested
from services.audit import audit_dimensions, audit_indexes, audit_materials
from services.audit_service import match_three_lines
from services.audit_runtime.state_transitions import (
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
from services.context_service import build_sheet_contexts
from services.task_planner_service import build_audit_tasks

logger = logging.getLogger(__name__)


class AuditCancelledError(RuntimeError):
    """用户手动中断审核。"""


def _raise_if_cancelled(project_id: str) -> None:
    if is_cancel_requested(project_id):
        raise AuditCancelledError("用户手动中断审核")


def execute_pipeline(project_id: str, audit_version: int, *, clear_running) -> None:  # noqa: ANN001
    """后台线程执行审核流程（按 audit_tasks 驱动）。"""
    try:
        _raise_if_cancelled(project_id)
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
            if summary["total"] == 0 or summary["ready"] != summary["total"]:
                raise RuntimeError(
                    "三线匹配未完成："
                    f"总数{summary['total']}，就绪{summary['ready']}，"
                    f"缺PNG{summary['missing_png']}，缺JSON{summary['missing_json']}，"
                    f"都缺{summary['missing_all']}"
                )
        finally:
            db.close()

        update_run_progress(
            project_id,
            audit_version,
            current_step="构建图纸上下文",
            progress=10,
        )
        _raise_if_cancelled(project_id)
        db = SessionLocal()
        try:
            build_sheet_contexts(project_id, db)
        finally:
            db.close()

        update_run_progress(
            project_id,
            audit_version,
            current_step="规划审核任务图",
            progress=15,
        )
        _raise_if_cancelled(project_id)
        db = SessionLocal()
        try:
            build_audit_tasks(project_id, audit_version, db)
        finally:
            db.close()

        all_tasks = load_tasks(project_id, audit_version)
        if not all_tasks:
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
        set_project_status(project_id, "ready")
    finally:
        clear_cancel_request(project_id)
        clear_running(project_id)
