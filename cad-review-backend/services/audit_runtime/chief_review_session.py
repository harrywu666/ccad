"""主审会话最小实现。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.audit_runtime.review_task_schema import HypothesisCard, WorkerTaskCard


def _infer_worker_kind(hypothesis: HypothesisCard) -> str:
    suggested = str(hypothesis.context.get("suggested_worker_kind") or "").strip()
    if suggested:
        return suggested
    text = f"{hypothesis.topic} {hypothesis.objective}".strip()
    if "标高" in text:
        return "elevation_consistency"
    if "材料" in text:
        return "material_semantic_consistency"
    if "索引" in text or "引用" in text:
        return "index_reference"
    if "节点" in text and ("归属" in text or "母图" in text):
        return "node_host_binding"
    return "spatial_consistency"


def _normalize_hypothesis(raw: dict[str, Any], index: int) -> HypothesisCard:
    hypothesis_id = str(raw.get("id") or f"hypothesis-{index + 1}").strip()
    return HypothesisCard(
        id=hypothesis_id,
        topic=str(raw.get("topic") or "").strip(),
        objective=str(raw.get("objective") or raw.get("topic") or "").strip(),
        source_sheet_no=str(raw.get("source_sheet_no") or "").strip(),
        target_sheet_nos=[
            str(item).strip()
            for item in list(raw.get("target_sheet_nos") or [])
            if str(item).strip()
        ],
        priority=float(raw.get("priority") or 0.5),
        context=dict(raw.get("context") or {}),
    )


@dataclass
class ChiefReviewSession:
    project_id: str
    audit_version: int
    agent_key: str = "chief_review_agent"

    def plan_worker_tasks(self, memory: dict[str, Any]) -> list[WorkerTaskCard]:
        tasks: list[WorkerTaskCard] = []
        active_hypotheses = list((memory or {}).get("active_hypotheses") or [])
        for index, raw in enumerate(active_hypotheses):
            hypothesis = _normalize_hypothesis(dict(raw or {}), index)
            worker_kind = _infer_worker_kind(hypothesis)
            tasks.append(
                WorkerTaskCard(
                    id=f"{hypothesis.id}:{worker_kind}",
                    hypothesis_id=hypothesis.id,
                    worker_kind=worker_kind,
                    objective=hypothesis.objective,
                    source_sheet_no=hypothesis.source_sheet_no,
                    target_sheet_nos=list(hypothesis.target_sheet_nos),
                    anchor_hint=dict(hypothesis.context.get("anchor_hint") or {}),
                    context={
                        "project_id": self.project_id,
                        "audit_version": self.audit_version,
                        "priority": hypothesis.priority,
                        **hypothesis.context,
                    },
                )
            )
        return tasks


__all__ = ["ChiefReviewSession"]
