"""副审 skill 执行合同。"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from services.audit_runtime.review_task_schema import WorkerResultCard, WorkerTaskCard
from services.audit_runtime.worker_conclusion_schema import WorkerConclusion
from services.audit_runtime.worker_skill_loader import WorkerSkillBundle


WorkerSkillCallable = Callable[..., Awaitable[WorkerResultCard]]


@dataclass(frozen=True)
class WorkerSkillExecutor:
    worker_kind: str
    skill_bundle: WorkerSkillBundle
    execute: WorkerSkillCallable


def build_task_event_meta(task: WorkerTaskCard) -> dict[str, Any]:
    context = dict(task.context or {})
    assignment_id = str(context.get("assignment_id") or "").strip()
    visible_session_key = str(context.get("visible_session_key") or "").strip()
    if assignment_id and not visible_session_key:
        visible_session_key = f"assignment:{assignment_id}"

    payload: dict[str, Any] = {}
    if assignment_id:
        payload["assignment_id"] = assignment_id
    if visible_session_key:
        payload["visible_session_key"] = visible_session_key
    return payload


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
    anchors: list[dict[str, Any]] | None = None,
    raw_skill_outputs: list[dict[str, Any]] | None = None,
    markdown_conclusion: str | None = None,
    evidence_bundle: dict[str, Any] | None = None,
    escalate_to_chief: bool = False,
    meta: dict[str, Any] | None = None,
) -> WorkerResultCard:
    assignment_id = str((task.context or {}).get("assignment_id") or "").strip() or None
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
    if assignment_id:
        merged_meta["assignment_id"] = assignment_id
        merged_meta["visible_session_key"] = f"assignment:{assignment_id}"
    if meta:
        merged_meta.update(meta)
    anchor_payloads = list(anchors or [])
    normalized_evidence = list(evidence or [])
    normalized_raw_outputs = list(raw_skill_outputs or [])
    conclusion = WorkerConclusion(
        markdown_conclusion=markdown_conclusion or _render_worker_markdown(
            task=task,
            summary=summary,
            status=status,
            confidence=confidence,
        ),
        evidence_bundle={
            "assignment_id": assignment_id,
            "task_id": task.id,
            "worker_kind": task.worker_kind,
            "rule_id": rule_id,
            "evidence_pack_id": evidence_pack_id,
            "review_round": int(merged_meta.get("review_round") or 1),
            "summary": summary,
            "grounding_status": _resolve_grounding_status(anchor_payloads),
            "anchors": anchor_payloads,
            "evidence": normalized_evidence,
            "raw_skill_outputs": normalized_raw_outputs,
            **(evidence_bundle or {}),
        },
    )
    return WorkerResultCard(
        task_id=task.id,
        hypothesis_id=task.hypothesis_id,
        worker_kind=task.worker_kind,
        status=status,
        confidence=confidence,
        summary=summary,
        evidence=normalized_evidence,
        markdown_conclusion=conclusion.markdown_conclusion,
        evidence_bundle=conclusion.evidence_bundle.model_dump(),
        escalate_to_chief=escalate_to_chief,
        meta=merged_meta,
    )


def extract_anchors_from_issue_results(results: list[Any]) -> list[dict[str, Any]]:
    anchors: list[dict[str, Any]] = []
    for item in results:
        raw_payload = getattr(item, "evidence_json", None)
        if raw_payload is None and isinstance(item, dict):
            raw_payload = item.get("evidence_json")
        if not raw_payload:
            continue
        try:
            payload = json.loads(str(raw_payload))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        for anchor in list(payload.get("anchors") or []):
            if isinstance(anchor, dict):
                anchors.append(dict(anchor))
    return anchors


def _render_worker_markdown(
    *,
    task: WorkerTaskCard,
    summary: str,
    status: str,
    confidence: float,
) -> str:
    target_text = "、".join([item for item in task.target_sheet_nos if str(item or "").strip()]) or "单图复核"
    return "\n".join(
        [
            "## 任务结论",
            f"- 任务：{task.objective}",
            f"- 范围：{task.source_sheet_no} -> {target_text}",
            f"- 状态：{status}",
            f"- 置信度：{confidence:.2f}",
            f"- 结论：{summary}",
        ]
    )


def _resolve_grounding_status(anchors: list[dict[str, Any]]) -> str:
    if not anchors:
        return "missing"
    if any(_has_grounding(anchor) for anchor in anchors):
        return "grounded"
    return "weak"


def _has_grounding(anchor: dict[str, Any]) -> bool:
    if not isinstance(anchor, dict):
        return False
    global_pct = anchor.get("global_pct")
    if isinstance(global_pct, dict) and global_pct.get("x") is not None and global_pct.get("y") is not None:
        return True
    highlight_region = anchor.get("highlight_region")
    if not isinstance(highlight_region, dict):
        return False
    bbox = highlight_region.get("bbox_pct")
    if not isinstance(bbox, dict):
        return False
    width = bbox.get("width", bbox.get("w"))
    height = bbox.get("height", bbox.get("h"))
    try:
        return float(width) > 0 and float(height) > 0
    except (TypeError, ValueError):
        return False


__all__ = [
    "WorkerSkillCallable",
    "WorkerSkillExecutor",
    "build_task_event_meta",
    "build_worker_skill_result",
    "extract_anchors_from_issue_results",
]
