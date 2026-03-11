"""Runner 用来恢复总控 Agent 的项目级记忆。"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List

from database import SessionLocal
from models import AuditRun, AuditRunEvent, AuditTask


@dataclass(slots=True)
class ProjectRecoveryMemory:
    project_id: str
    audit_version: int
    current_stage: str = ""
    task_summary: Dict[str, int] = field(default_factory=dict)
    recent_agent_reports: List[Dict[str, Any]] = field(default_factory=list)
    recent_master_actions: List[Dict[str, Any]] = field(default_factory=list)
    recent_runner_decisions: List[Dict[str, Any]] = field(default_factory=list)
    risk_summary: Dict[str, Any] = field(default_factory=dict)
    master_status_summary: Dict[str, Any] = field(default_factory=dict)


def _safe_meta(row) -> Dict[str, Any]:  # noqa: ANN001
    if not getattr(row, "meta_json", None):
        return {}
    try:
        payload = json.loads(row.meta_json)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_project_recovery_memory(project_id: str, *, audit_version: int) -> ProjectRecoveryMemory:
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
        tasks = (
            db.query(AuditTask)
            .filter(
                AuditTask.project_id == project_id,
                AuditTask.audit_version == int(audit_version),
            )
            .all()
        )
        rows = (
            db.query(AuditRunEvent)
            .filter(
                AuditRunEvent.project_id == project_id,
                AuditRunEvent.audit_version == int(audit_version),
            )
            .order_by(AuditRunEvent.id.desc())
            .limit(30)
            .all()
        )
    finally:
        db.close()

    task_summary: Dict[str, int] = {"pending": 0, "running": 0, "done": 0, "failed": 0}
    for task in tasks:
        status = str(getattr(task, "status", "") or "").strip() or "pending"
        task_summary[status] = int(task_summary.get(status, 0)) + 1

    recent_agent_reports: List[Dict[str, Any]] = []
    recent_master_actions: List[Dict[str, Any]] = []
    recent_runner_decisions: List[Dict[str, Any]] = []
    risk_summary = {"agent_status_reported_count": 0, "master_recovery_requested_count": 0}

    for row in reversed(rows):
        meta = _safe_meta(row)
        event_kind = str(getattr(row, "event_kind", "") or "").strip()
        agent_key = str(getattr(row, "agent_key", "") or "").strip()
        item = {
            "event_kind": event_kind,
            "agent_key": agent_key,
            "agent_name": str(getattr(row, "agent_name", "") or "").strip(),
            "message": str(getattr(row, "message", "") or "").strip(),
            "meta": meta,
        }
        if event_kind == "agent_status_reported":
            recent_agent_reports.append(item)
            risk_summary["agent_status_reported_count"] += 1
        if agent_key == "master_planner_agent" or event_kind.startswith("master_"):
            recent_master_actions.append(item)
            if event_kind == "master_recovery_requested":
                risk_summary["master_recovery_requested_count"] += 1
        if event_kind == "runner_observer_decision":
            recent_runner_decisions.append(item)

    return ProjectRecoveryMemory(
        project_id=project_id,
        audit_version=int(audit_version),
        current_stage=str(getattr(run, "current_step", "") or "").strip(),
        task_summary=task_summary,
        recent_agent_reports=recent_agent_reports[-5:],
        recent_master_actions=recent_master_actions[-5:],
        recent_runner_decisions=recent_runner_decisions[-5:],
        risk_summary=risk_summary,
        master_status_summary={
            "run_status": str(getattr(run, "status", "") or "").strip(),
            "progress": getattr(run, "progress", 0),
            "current_step": str(getattr(run, "current_step", "") or "").strip(),
        },
    )


__all__ = [
    "ProjectRecoveryMemory",
    "load_project_recovery_memory",
]
