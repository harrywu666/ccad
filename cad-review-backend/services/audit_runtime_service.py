"""
审核运行时服务
提供异步审核任务启动、进度查询、运行状态管理能力。
审核流水线执行逻辑统一由 services.audit_runtime.orchestrator 提供。
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime
from typing import Dict, Optional

from database import SessionLocal
from models import AuditResult, AuditRun, AuditTask

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


def mark_stale_running_runs(project_id: str, db, reason: str = "任务已中断（服务重启或人工停止）") -> int:
    """将数据库中遗留的 running 记录标记为 failed，避免出现僵尸运行态。"""
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


def start_audit_async(
    project_id: str,
    audit_version: int,
    *,
    allow_incomplete: bool = False,
    provider_mode: Optional[str] = None,
) -> None:
    """启动后台审核线程（调用方需已持有 _set_running 锁）。"""
    from services.audit_runtime.orchestrator import execute_pipeline

    worker = threading.Thread(
        target=execute_pipeline,
        args=(project_id, audit_version),
        kwargs={"allow_incomplete": allow_incomplete, "clear_running": _clear_running},
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
            "scope_mode": None,
            "scope_summary": None,
        }

    return {
        "audit_version": run.audit_version,
        "status": run.status,
        "current_step": run.current_step,
        "progress": run.progress,
        "total_issues": run.total_issues,
        "provider_mode": getattr(run, "provider_mode", None),
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "scope_mode": getattr(run, "scope_mode", None),
        "scope_summary": getattr(run, "scope_summary", None),
    }
