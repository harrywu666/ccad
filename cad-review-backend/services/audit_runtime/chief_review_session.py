"""主审会话最小实现。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from domain.sheet_normalization import normalize_sheet_no
from services.audit_runtime.review_task_schema import HypothesisCard, ReviewAssignment, WorkerTaskCard
from services.audit_runtime.worker_skill_registry import is_skillized_worker


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


def _build_worker_session_key(worker_kind: str, source_sheet_no: str, target_sheet_nos: list[str]) -> str:
    normalized_source = normalize_sheet_no(source_sheet_no) or "UNKNOWN"
    normalized_targets = [
        normalize_sheet_no(item)
        for item in list(target_sheet_nos or [])
        if normalize_sheet_no(item)
    ]
    target_part = "__".join(normalized_targets) if normalized_targets else "SELF"
    return f"worker_skill:{worker_kind}:{normalized_source}:{target_part}"


def _resolve_evidence_selection_policy(worker_kind: str) -> str:
    normalized = str(worker_kind or "").strip()
    if normalized == "index_reference":
        return "source_sheet_indexes_with_target_refs"
    if normalized == "material_semantic_consistency":
        return "source_target_material_context"
    if normalized == "node_host_binding":
        return "source_target_linked_pair"
    if normalized in {"elevation_consistency", "spatial_consistency"}:
        return "paired_full_with_single_sheet_semantics"
    return "worker_default_context"


def _default_expected_evidence_types(worker_kind: str) -> list[str]:
    normalized = str(worker_kind or "").strip()
    if normalized in {"elevation_consistency", "spatial_consistency", "node_host_binding"}:
        return ["anchors", "paired_context"]
    if normalized in {"index_reference", "material_semantic_consistency"}:
        return ["anchors", "sheet_context"]
    return ["anchors"]


def _split_assignment_targets(hypothesis: HypothesisCard) -> list[list[str]]:
    targets = list(hypothesis.target_sheet_nos) or [hypothesis.source_sheet_no]
    if len(targets) <= 2:
        return [targets]
    return [[target] for target in targets]


def _build_assignment_id(hypothesis_id: str, assignment_count: int) -> str:
    if assignment_count <= 1:
        return hypothesis_id
    return f"{hypothesis_id}::part-{assignment_count}"


@dataclass
class ChiefReviewSession:
    project_id: str
    audit_version: int
    agent_key: str = "chief_review_agent"

    def plan_assignments(self, memory: dict[str, Any]) -> list[ReviewAssignment]:
        assignments: list[ReviewAssignment] = []
        active_hypotheses = list((memory or {}).get("active_hypotheses") or [])
        for index, raw in enumerate(active_hypotheses):
            hypothesis = _normalize_hypothesis(dict(raw or {}), index)
            worker_kind = _infer_worker_kind(hypothesis)
            target_groups = _split_assignment_targets(hypothesis)
            for part_index, target_sheet_nos in enumerate(target_groups, start=1):
                target_label = ", ".join(target_sheet_nos)
                assignments.append(
                    ReviewAssignment(
                        assignment_id=_build_assignment_id(hypothesis.id, len(target_groups) if len(target_groups) > 1 else 1)
                        if len(target_groups) == 1
                        else f"{hypothesis.id}::part-{part_index}",
                        review_intent=worker_kind,
                        source_sheet_no=hypothesis.source_sheet_no,
                        target_sheet_nos=list(target_sheet_nos),
                        task_title=f"{hypothesis.source_sheet_no} -> {target_label}"
                        if target_label and target_label != hypothesis.source_sheet_no
                        else (hypothesis.objective or hypothesis.topic),
                        acceptance_criteria=[hypothesis.objective or hypothesis.topic],
                        expected_evidence_types=_default_expected_evidence_types(worker_kind),
                        priority=hypothesis.priority,
                        dispatch_reason="chief_dispatch",
                    )
                )
        return assignments

    def next_assignment(self, assignments: list[ReviewAssignment]) -> ReviewAssignment | None:
        return assignments[0] if assignments else None

    def build_worker_task_from_assignment(self, assignment: ReviewAssignment) -> WorkerTaskCard:
        worker_kind = str(assignment.review_intent).strip()
        target_sheet_nos = list(assignment.target_sheet_nos)
        if target_sheet_nos == [assignment.source_sheet_no]:
            target_sheet_nos = []
        session_key = _build_worker_session_key(
            worker_kind,
            assignment.source_sheet_no,
            target_sheet_nos,
        )
        evidence_selection_policy = _resolve_evidence_selection_policy(worker_kind)
        hypothesis_id = str(assignment.assignment_id).split("::", 1)[0]
        context = {
            "project_id": self.project_id,
            "audit_version": self.audit_version,
            "priority": assignment.priority,
            "planner_source": "chief_agent",
            "assignment_id": assignment.assignment_id,
            "session_key": session_key,
            "evidence_selection_policy": evidence_selection_policy,
            "dispatch_reason": assignment.dispatch_reason,
        }
        if is_skillized_worker(worker_kind):
            context.setdefault("execution_mode", "worker_skill")
            context.setdefault("skill_id", worker_kind)
            context.setdefault("skill_mode", "worker_skill")
            context.setdefault("prompt_source", "agent_skill")
        return WorkerTaskCard(
            id=assignment.assignment_id,
            hypothesis_id=hypothesis_id,
            worker_kind=worker_kind,
            skill_id=worker_kind,
            session_key=session_key,
            evidence_selection_policy=evidence_selection_policy,
            objective=assignment.task_title,
            source_sheet_no=assignment.source_sheet_no,
            target_sheet_nos=target_sheet_nos,
            anchor_hint={},
            context=context,
        )

    def plan_worker_tasks(self, memory: dict[str, Any]) -> list[WorkerTaskCard]:
        return [
            self.build_worker_task_from_assignment(assignment)
            for assignment in self.plan_assignments(memory)
        ]


__all__ = ["ChiefReviewSession"]
