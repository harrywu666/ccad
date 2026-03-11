"""
审核运行时服务
提供异步审核任务启动、进度查询、运行状态管理能力。
审核流水线执行逻辑统一由 services.audit_runtime.orchestrator 提供。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict, Optional

from database import SessionLocal
from models import AuditResult, AuditRun, AuditRunEvent, AuditTask

_running_lock = threading.Lock()
_running_projects: set[str] = set()
_running_workers: dict[str, threading.Thread] = {}
_worker_generations: dict[str, int] = {}
logger = logging.getLogger(__name__)

_PLANNING_STEP_TITLES = {
    "prepare": "准备检查",
    "context": "构建图纸上下文",
    "relationship_discovery": "AI 分析图纸关系",
    "task_planning": "规划审核任务图",
}


def _set_running(project_id: str) -> bool:
    with _running_lock:
        if project_id in _running_projects:
            return False
        _running_projects.add(project_id)
        _worker_generations.setdefault(project_id, 1)
        return True


def _clear_running(project_id: str, *, generation: int | None = None) -> None:
    with _running_lock:
        current_generation = _worker_generations.get(project_id)
        if generation is not None and current_generation is not None and generation != current_generation:
            return
        _running_projects.discard(project_id)
        _running_workers.pop(project_id, None)
        _worker_generations.pop(project_id, None)


def is_project_running(project_id: str) -> bool:
    with _running_lock:
        return project_id in _running_projects


def register_project_worker(project_id: str, worker: threading.Thread) -> None:
    with _running_lock:
        _running_workers[project_id] = worker


def register_project_worker_generation(project_id: str, generation: int) -> None:
    with _running_lock:
        _worker_generations[project_id] = int(generation)


def get_project_worker_generation(project_id: str) -> int:
    with _running_lock:
        return int(_worker_generations.get(project_id, 0))


def is_worker_generation_current(project_id: str, generation: int) -> bool:
    with _running_lock:
        return int(_worker_generations.get(project_id, 0)) == int(generation)


def bump_project_worker_generation(project_id: str) -> int:
    with _running_lock:
        next_generation = int(_worker_generations.get(project_id, 0)) + 1
        _worker_generations[project_id] = next_generation
        _running_projects.add(project_id)
        return next_generation


def wait_for_project_stop(project_id: str, timeout_seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_seconds)

    while time.monotonic() < deadline:
        with _running_lock:
            worker = _running_workers.get(project_id)
            running = project_id in _running_projects

        if worker is not None:
            remaining = max(0.0, deadline - time.monotonic())
            worker.join(min(0.2, remaining))
            if not worker.is_alive():
                return True
            continue

        if not running:
            return True

        time.sleep(0.1)

    with _running_lock:
        worker = _running_workers.get(project_id)
        running = project_id in _running_projects
    return (worker is None or not worker.is_alive()) and not running


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
    resume_existing: bool = False,
    worker_generation: Optional[int] = None,
) -> None:
    """启动后台审核线程（调用方需已持有 _set_running 锁）。"""
    from services.audit_runtime.orchestrator import execute_pipeline

    generation = int(worker_generation or 0) or max(1, get_project_worker_generation(project_id))
    register_project_worker_generation(project_id, generation)

    worker = threading.Thread(
        target=execute_pipeline,
        args=(project_id, audit_version),
        kwargs={
            "allow_incomplete": allow_incomplete,
            "clear_running": lambda pid: _clear_running(pid, generation=generation),
            "resume_existing": resume_existing,
            "worker_generation": generation,
            "is_current_worker": is_worker_generation_current,
        },
        daemon=True,
    )
    register_project_worker(project_id, worker)
    worker.start()


def restart_master_agent_async(project_id: str, audit_version: int) -> Dict[str, object]:
    db = SessionLocal()
    try:
        run = (
            db.query(AuditRun)
            .filter(
                AuditRun.project_id == project_id,
                AuditRun.audit_version == int(audit_version),
            )
            .first()
        )
        if not run:
            return {"restarted": False, "reason": "run_not_found"}
        run.status = "running"
        run.current_step = "总控恢复中"
        run.error = None
        run.updated_at = datetime.now()
        db.commit()
        provider_mode = getattr(run, "provider_mode", None)
        allow_incomplete = str(getattr(run, "scope_mode", "") or "").strip() == "partial"
    finally:
        db.close()

    generation = bump_project_worker_generation(project_id)
    start_audit_async(
        project_id,
        int(audit_version),
        allow_incomplete=allow_incomplete,
        provider_mode=provider_mode,
        resume_existing=True,
        worker_generation=generation,
    )
    return {
        "restarted": True,
        "generation": generation,
        "provider_mode": provider_mode,
        "resume_existing": True,
    }


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


def _resolve_planning_step_title(step_key: Optional[str]) -> Optional[str]:
    key = (step_key or "").strip().lower()
    if not key:
        return None
    return _PLANNING_STEP_TITLES.get(key)


def build_recent_event_snapshot(
    project_id: str,
    db,
    *,
    max_age_seconds: int = 900,
) -> Dict[str, object]:
    latest_event = (
        db.query(AuditRunEvent)
        .filter(AuditRunEvent.project_id == project_id)
        .order_by(AuditRunEvent.created_at.desc(), AuditRunEvent.id.desc())
        .first()
    )
    if not latest_event:
        return build_run_snapshot(None)

    if latest_event.created_at and latest_event.created_at < datetime.now() - timedelta(seconds=max_age_seconds):
        return build_run_snapshot(None)

    meta: Dict[str, object] = {}
    if latest_event.meta_json:
        try:
            payload = json.loads(latest_event.meta_json)
            if isinstance(payload, dict):
                meta = payload
        except Exception:
            meta = {}

    provider_mode = meta.get("provider_mode") or meta.get("provider_name")
    progress = latest_event.progress_hint
    if progress is None:
        progress = {
            "context": 10,
            "relationship_discovery": 12,
            "task_planning": 18,
        }.get((latest_event.step_key or "").strip().lower(), 8)

    return {
        "audit_version": latest_event.audit_version,
        "status": "planning",
        "current_step": _resolve_planning_step_title(latest_event.step_key) or latest_event.message,
        "progress": progress,
        "total_issues": 0,
        "provider_mode": provider_mode,
        "error": None,
        "started_at": latest_event.created_at.isoformat() if latest_event.created_at else None,
        "finished_at": None,
        "scope_mode": None,
        "scope_summary": None,
    }


def get_audit_started_at_from_events(
    project_id: str,
    audit_version: Optional[int],
    db,
) -> Optional[str]:
    if audit_version is None:
        return None

    earliest_event = (
        db.query(AuditRunEvent)
        .filter(
            AuditRunEvent.project_id == project_id,
            AuditRunEvent.audit_version == audit_version,
        )
        .order_by(AuditRunEvent.created_at.asc(), AuditRunEvent.id.asc())
        .first()
    )
    if not earliest_event or not earliest_event.created_at:
        return None
    return earliest_event.created_at.isoformat()
