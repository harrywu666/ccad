"""总控 Agent 的子 Agent 恢复账本。"""

from __future__ import annotations

from dataclasses import asdict

from database import SessionLocal
from models import AuditTask
from services.audit_runtime.state_transitions import append_task_trace
from services.audit_runtime.task_recovery_memory import TaskRecoveryMemory


MAX_SUBAGENT_RESTARTS = 3


def can_retry_subagent(memory: TaskRecoveryMemory, *, max_restarts: int = MAX_SUBAGENT_RESTARTS) -> bool:
    return int(memory.restart_count) < int(max_restarts)


def record_recovery_attempt(
    project_id: str,
    audit_version: int,
    *,
    memory: TaskRecoveryMemory,
    reason: str,
) -> int:
    next_restart_count = int(memory.restart_count) + 1
    db = SessionLocal()
    try:
        rows = (
            db.query(AuditTask)
            .filter(
                AuditTask.project_id == project_id,
                AuditTask.audit_version == audit_version,
                AuditTask.id.in_(memory.task_ids),
            )
            .all()
        )
        for task in rows:
            append_task_trace(
                task,
                {
                    "event": "master_recovery_attempted",
                    "restart_count": next_restart_count,
                    "reason": str(reason or "").strip(),
                    "memory": asdict(memory),
                },
            )
        db.commit()
    finally:
        db.close()
    return next_restart_count


def record_recovery_success(
    project_id: str,
    audit_version: int,
    *,
    memory: TaskRecoveryMemory,
    restart_count: int,
) -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(AuditTask)
            .filter(
                AuditTask.project_id == project_id,
                AuditTask.audit_version == audit_version,
                AuditTask.id.in_(memory.task_ids),
            )
            .all()
        )
        for task in rows:
            append_task_trace(
                task,
                {
                    "event": "master_recovery_succeeded",
                    "restart_count": int(restart_count),
                    "memory": asdict(memory),
                },
            )
        db.commit()
    finally:
        db.close()


def record_recovery_exhausted(
    project_id: str,
    audit_version: int,
    *,
    memory: TaskRecoveryMemory,
    reason: str,
) -> None:
    db = SessionLocal()
    try:
        rows = (
            db.query(AuditTask)
            .filter(
                AuditTask.project_id == project_id,
                AuditTask.audit_version == audit_version,
                AuditTask.id.in_(memory.task_ids),
            )
            .all()
        )
        for task in rows:
            task.result_ref = "permanently_failed"
            append_task_trace(
                task,
                {
                    "event": "master_recovery_exhausted",
                    "restart_count": int(memory.restart_count),
                    "reason": str(reason or "").strip(),
                    "memory": asdict(memory),
                },
            )
        db.commit()
    finally:
        db.close()


__all__ = [
    "MAX_SUBAGENT_RESTARTS",
    "can_retry_subagent",
    "record_recovery_attempt",
    "record_recovery_success",
    "record_recovery_exhausted",
]
