"""
审核运行时服务
提供异步审核任务启动、执行、进度更新能力
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from database import SessionLocal
from models import AuditResult, AuditRun, AuditTask, Project
from services.audit import audit_dimensions, audit_indexes, audit_materials
from services.audit_service import match_three_lines
from services.cache_service import increment_cache_version
from services.context_service import build_sheet_contexts
from services.task_planner_service import build_audit_tasks

_running_lock = threading.Lock()
_running_projects: set[str] = set()
logger = logging.getLogger(__name__)


def _set_running(project_id: str) -> bool:
    with _running_lock:
        if project_id in _running_projects:
            return False
        _running_projects.add(project_id)
        return True


def _clear_running(project_id: str) -> None:
    with _running_lock:
        _running_projects.discard(project_id)


def is_project_running(project_id: str) -> bool:
    with _running_lock:
        return project_id in _running_projects


def get_latest_run(project_id: str, db) -> Optional[AuditRun]:
    return (
        db.query(AuditRun)
        .filter(AuditRun.project_id == project_id)
        .order_by(AuditRun.audit_version.desc(), AuditRun.created_at.desc())
        .first()
    )


def get_next_audit_version(project_id: str, db) -> int:
    latest_run = get_latest_run(project_id, db)
    latest_result = (
        db.query(AuditResult)
        .filter(AuditResult.project_id == project_id)
        .order_by(AuditResult.audit_version.desc())
        .first()
    )
    max_run_ver = latest_run.audit_version if latest_run else 0
    max_result_ver = latest_result.audit_version if latest_result else 0
    return max(max_run_ver, max_result_ver) + 1


def mark_stale_running_runs(project_id: str, db, reason: str = "任务已中断（服务重启或人工停止）") -> int:
    """
    将数据库中遗留的 running 记录标记为 failed，避免出现僵尸运行态。
    """
    stale_runs = (
        db.query(AuditRun)
        .filter(
            AuditRun.project_id == project_id,
            AuditRun.status == "running",
        )
        .all()
    )
    if not stale_runs:
        return 0

    now = datetime.now()
    stale_versions = {run.audit_version for run in stale_runs}
    for run in stale_runs:
        run.status = "failed"
        run.current_step = "执行中断"
        run.error = run.error or reason
        run.finished_at = run.finished_at or now
        run.updated_at = now

    stale_tasks = (
        db.query(AuditTask)
        .filter(
            AuditTask.project_id == project_id,
            AuditTask.audit_version.in_(stale_versions),
            AuditTask.status == "running",
        )
        .all()
    )
    for task in stale_tasks:
        task.status = "failed"
        _append_task_trace(
            task,
            {
                "at": now.isoformat(),
                "status": "failed",
                "note": "stale_run_recovered",
            },
        )

    db.commit()
    logger.warning(
        "project=%s stale running runs recovered: count=%s versions=%s",
        project_id,
        len(stale_runs),
        sorted(stale_versions),
    )
    return len(stale_runs)


def _update_run_progress(
    project_id: str,
    audit_version: int,
    *,
    status: Optional[str] = None,
    current_step: Optional[str] = None,
    progress: Optional[int] = None,
    total_issues: Optional[int] = None,
    error: Optional[str] = None,
    finished: bool = False,
) -> None:
    db = SessionLocal()
    try:
        run = (
            db.query(AuditRun)
            .filter(
                AuditRun.project_id == project_id,
                AuditRun.audit_version == audit_version,
            )
            .first()
        )
        if not run:
            return

        if status is not None:
            run.status = status
        if current_step is not None:
            run.current_step = current_step
        if progress is not None:
            run.progress = max(0, min(100, int(progress)))
        if total_issues is not None:
            run.total_issues = int(total_issues)
        if error is not None:
            run.error = error
        if finished:
            run.finished_at = datetime.now()

        run.updated_at = datetime.now()
        db.commit()
    finally:
        db.close()


def _set_project_status(project_id: str, status: str) -> None:
    db = SessionLocal()
    try:
        project = db.query(Project).filter(Project.id == project_id).first()
        if not project:
            return
        project.status = status
        db.commit()
    finally:
        db.close()


def _norm_sheet_no(value: Optional[str]) -> str:
    if not value:
        return ""
    s = str(value).strip().upper()
    s = re.sub(r"[\s\-_./\\()（）【】\[\]{}:：|]+", "", s)
    return s


def _append_task_trace(task: AuditTask, payload: Dict[str, object]) -> None:
    if task.trace_json:
        try:
            trace = json.loads(task.trace_json)
            if not isinstance(trace, dict):
                trace = {"planner_raw": task.trace_json}
        except Exception:
            trace = {"planner_raw": task.trace_json}
    else:
        trace = {}

    runtime = trace.get("runtime")
    if not isinstance(runtime, list):
        runtime = []
    runtime.append(payload)
    trace["runtime"] = runtime[-30:]
    task.trace_json = json.dumps(trace, ensure_ascii=False)


def _set_task_status_batch(
    project_id: str,
    audit_version: int,
    task_ids: List[str],
    status: str,
    *,
    note: str,
    result_ref: Optional[str] = None,
) -> None:
    if not task_ids:
        return

    db = SessionLocal()
    try:
        rows = (
            db.query(AuditTask)
            .filter(
                AuditTask.project_id == project_id,
                AuditTask.audit_version == audit_version,
                AuditTask.id.in_(task_ids),
            )
            .all()
        )
        now = datetime.now().isoformat()
        for task in rows:
            task.status = status
            if result_ref is not None:
                task.result_ref = result_ref
            _append_task_trace(
                task,
                {
                    "at": now,
                    "status": status,
                    "note": note,
                },
            )
        db.commit()
    finally:
        db.close()


def _mark_running_tasks_failed(project_id: str, audit_version: int, note: str) -> None:
    db = SessionLocal()
    try:
        running_tasks = (
            db.query(AuditTask)
            .filter(
                AuditTask.project_id == project_id,
                AuditTask.audit_version == audit_version,
                AuditTask.status == "running",
            )
            .all()
        )
        if not running_tasks:
            return
        now = datetime.now().isoformat()
        for task in running_tasks:
            task.status = "failed"
            _append_task_trace(
                task,
                {
                    "at": now,
                    "status": "failed",
                    "note": note,
                },
            )
        db.commit()
    finally:
        db.close()


def _load_tasks(project_id: str, audit_version: int) -> List[AuditTask]:
    db = SessionLocal()
    try:
        return (
            db.query(AuditTask)
            .filter(
                AuditTask.project_id == project_id,
                AuditTask.audit_version == audit_version,
            )
            .order_by(AuditTask.priority.asc(), AuditTask.task_type.asc(), AuditTask.created_at.asc())
            .all()
        )
    finally:
        db.close()


def _progress_by_task(completed: int, total: int, *, base: int = 15, span: int = 80) -> int:
    if total <= 0:
        return base
    return base + int(span * completed / total)


def _task_group_pairs(tasks: List[AuditTask]) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    seen: set[Tuple[str, str]] = set()
    for task in tasks:
        src_raw = (task.source_sheet_no or "").strip()
        tgt_raw = (task.target_sheet_no or "").strip()
        src_key = _norm_sheet_no(src_raw)
        tgt_key = _norm_sheet_no(tgt_raw)
        if not src_key or not tgt_key or src_key == tgt_key:
            continue
        pair_key = tuple(sorted([src_key, tgt_key]))
        if pair_key in seen:
            continue
        seen.add(pair_key)
        pairs.append((src_raw, tgt_raw))
    return pairs


def _task_group_source_sheets(tasks: List[AuditTask]) -> List[str]:
    sheets: List[str] = []
    seen: set[str] = set()
    for task in tasks:
        raw = (task.source_sheet_no or "").strip()
        key = _norm_sheet_no(raw)
        if not raw or not key or key in seen:
            continue
        seen.add(key)
        sheets.append(raw)
    return sheets


def execute_audit_pipeline(project_id: str, audit_version: int) -> None:
    """后台线程执行审核流程（按 audit_tasks 驱动）"""
    try:
        _update_run_progress(
            project_id,
            audit_version,
            status="running",
            current_step="校验三线匹配",
            progress=5,
        )

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

        _update_run_progress(
            project_id,
            audit_version,
            current_step="构建图纸上下文",
            progress=10,
        )
        db = SessionLocal()
        try:
            build_sheet_contexts(project_id, db)
        finally:
            db.close()

        _update_run_progress(
            project_id,
            audit_version,
            current_step="规划审核任务图",
            progress=15,
        )
        db = SessionLocal()
        try:
            build_audit_tasks(project_id, audit_version, db)
        finally:
            db.close()

        all_tasks = _load_tasks(project_id, audit_version)
        if not all_tasks:
            raise RuntimeError("审核任务图为空，请先检查图纸上下文构建结果。")

        total_tasks = len(all_tasks)
        completed_tasks = 0
        total_issues = 0

        index_tasks = [t for t in all_tasks if t.task_type == "index"]
        dimension_tasks = [t for t in all_tasks if t.task_type == "dimension"]
        material_tasks = [t for t in all_tasks if t.task_type == "material"]
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
            _update_run_progress(
                project_id,
                audit_version,
                current_step=f"索引核对（{len(index_tasks)}任务）",
                progress=_progress_by_task(completed_tasks, total_tasks),
                total_issues=total_issues,
            )
            _set_task_status_batch(
                project_id,
                audit_version,
                [t.id for t in index_tasks],
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
                        source_sheet_filters=_task_group_source_sheets(index_tasks),
                    )
                finally:
                    db.close()
            except Exception:
                _set_task_status_batch(
                    project_id,
                    audit_version,
                    [t.id for t in index_tasks],
                    "failed",
                    note="index_audit_failed",
                )
                raise

            total_issues += len(index_issues)
            completed_tasks += len(index_tasks)
            _set_task_status_batch(
                project_id,
                audit_version,
                [t.id for t in index_tasks],
                "done",
                note=f"index_audit_done issues={len(index_issues)}",
                result_ref=f"index:{len(index_issues)}",
            )
            _update_run_progress(
                project_id,
                audit_version,
                current_step=f"索引核对完成（{len(index_tasks)}/{len(index_tasks)}）",
                progress=_progress_by_task(completed_tasks, total_tasks),
                total_issues=total_issues,
            )

        if dimension_tasks:
            pair_filters = _task_group_pairs(dimension_tasks)
            _update_run_progress(
                project_id,
                audit_version,
                current_step=f"尺寸核对（{len(dimension_tasks)}任务）",
                progress=_progress_by_task(completed_tasks, total_tasks),
                total_issues=total_issues,
            )
            _set_task_status_batch(
                project_id,
                audit_version,
                [t.id for t in dimension_tasks],
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
                _set_task_status_batch(
                    project_id,
                    audit_version,
                    [t.id for t in dimension_tasks],
                    "failed",
                    note="dimension_audit_failed",
                )
                raise

            total_issues += len(dimension_issues)
            completed_tasks += len(dimension_tasks)
            _set_task_status_batch(
                project_id,
                audit_version,
                [t.id for t in dimension_tasks],
                "done",
                note=f"dimension_audit_done issues={len(dimension_issues)} pairs={len(pair_filters)}",
                result_ref=f"dimension:{len(dimension_issues)}",
            )
            _update_run_progress(
                project_id,
                audit_version,
                current_step=f"尺寸核对完成（{len(dimension_tasks)}/{len(dimension_tasks)}）",
                progress=_progress_by_task(completed_tasks, total_tasks),
                total_issues=total_issues,
            )

        if material_tasks:
            source_filters = _task_group_source_sheets(material_tasks)
            _update_run_progress(
                project_id,
                audit_version,
                current_step=f"材料核对（{len(material_tasks)}任务）",
                progress=_progress_by_task(completed_tasks, total_tasks),
                total_issues=total_issues,
            )
            _set_task_status_batch(
                project_id,
                audit_version,
                [t.id for t in material_tasks],
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
                _set_task_status_batch(
                    project_id,
                    audit_version,
                    [t.id for t in material_tasks],
                    "failed",
                    note="material_audit_failed",
                )
                raise

            total_issues += len(material_issues)
            completed_tasks += len(material_tasks)
            _set_task_status_batch(
                project_id,
                audit_version,
                [t.id for t in material_tasks],
                "done",
                note=f"material_audit_done issues={len(material_issues)} sheets={len(source_filters)}",
                result_ref=f"material:{len(material_issues)}",
            )
            _update_run_progress(
                project_id,
                audit_version,
                current_step=f"材料核对完成（{len(material_tasks)}/{len(material_tasks)}）",
                progress=_progress_by_task(completed_tasks, total_tasks),
                total_issues=total_issues,
            )

        _update_run_progress(
            project_id,
            audit_version,
            status="done",
            current_step="审核完成",
            progress=100,
            total_issues=total_issues,
            finished=True,
        )
        _set_project_status(project_id, "done")

        db = SessionLocal()
        try:
            increment_cache_version(project_id, db)
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001
        _mark_running_tasks_failed(project_id, audit_version, f"pipeline_failed:{str(exc)}")
        _update_run_progress(
            project_id,
            audit_version,
            status="failed",
            current_step="执行失败",
            error=str(exc),
            finished=True,
        )
        _set_project_status(project_id, "ready")
    finally:
        _clear_running(project_id)


def start_audit_async(project_id: str, audit_version: int) -> None:
    """启动后台审核线程（调用方需已持有 _set_running 锁）。"""
    worker = threading.Thread(
        target=execute_audit_pipeline,
        args=(project_id, audit_version),
        daemon=True,
    )
    worker.start()


def build_run_snapshot(run: Optional[AuditRun]) -> Dict[str, object]:
    if not run:
        return {
            "audit_version": None,
            "status": "idle",
            "current_step": None,
            "progress": 0,
            "total_issues": 0,
            "error": None,
            "started_at": None,
            "finished_at": None,
        }

    return {
        "audit_version": run.audit_version,
        "status": run.status,
        "current_step": run.current_step,
        "progress": run.progress,
        "total_issues": run.total_issues,
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
    }
