"""副审 skill 执行合同。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from services.audit_runtime.review_task_schema import WorkerResultCard, WorkerTaskCard
from services.audit_runtime.worker_skill_loader import WorkerSkillBundle


WorkerSkillCallable = Callable[..., Awaitable[WorkerResultCard]]


@dataclass(frozen=True)
class WorkerSkillExecutor:
    worker_kind: str
    skill_bundle: WorkerSkillBundle
    execute: WorkerSkillCallable


def build_worker_skill_result(
    *,
    task: WorkerTaskCard,
    skill_bundle: WorkerSkillBundle,
    status: str,
    confidence: float,
    summary: str,
    rule_id: str,
    evidence_pack_id: str,
    evidence: list[dict[str, Any]] | None = None,
    escalate_to_chief: bool = False,
    meta: dict[str, Any] | None = None,
) -> WorkerResultCard:
    merged_meta = {
        "compat_mode": "native_worker",
        "skill_mode": "worker_skill",
        "skill_id": skill_bundle.worker_kind,
        "skill_path": str(skill_bundle.skill_path),
        "skill_version": skill_bundle.skill_version,
        "prompt_source": "agent_skill",
        "session_key": task.session_key,
        "evidence_selection_policy": task.evidence_selection_policy,
        "task_stage": "worker_skill_execution",
        "sheet_no": task.source_sheet_no,
        "location": task.objective,
        "rule_id": rule_id,
        "evidence_pack_id": evidence_pack_id,
    }
    if meta:
        merged_meta.update(meta)
    return WorkerResultCard(
        task_id=task.id,
        hypothesis_id=task.hypothesis_id,
        worker_kind=task.worker_kind,
        status=status,
        confidence=confidence,
        summary=summary,
        evidence=list(evidence or []),
        escalate_to_chief=escalate_to_chief,
        meta=merged_meta,
    )


__all__ = ["WorkerSkillCallable", "WorkerSkillExecutor", "build_worker_skill_result"]
