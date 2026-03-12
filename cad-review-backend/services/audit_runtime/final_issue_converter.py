"""把 organizer Markdown 与证据包转换成最终 FinalIssue。"""

from __future__ import annotations

import re
from typing import Any

from services.audit_runtime.final_review_schema import FinalIssue


def _read_field(payload: Any, key: str, default: Any = "") -> Any:
    if isinstance(payload, dict):
        return payload.get(key, default)
    return getattr(payload, key, default)


def _split_markdown_blocks(markdown: str) -> list[str]:
    text = str(markdown or "").strip()
    if not text:
        return []
    parts = re.split(r"(?=^##\s+问题\s+\d+\s*$)", text, flags=re.MULTILINE)
    return [part.strip() for part in parts if str(part).strip()]


def _worker_kind_to_finding_type(worker_kind: str) -> str:
    mapping = {
        "elevation_consistency": "dim_mismatch",
        "spatial_consistency": "dim_mismatch",
        "material_semantic_consistency": "material_conflict",
        "index_reference": "index_conflict",
        "node_host_binding": "missing_ref",
    }
    return mapping.get(str(worker_kind or "").strip(), "unknown")


def _worker_kind_to_recommendation(worker_kind: str) -> str:
    mapping = {
        "elevation_consistency": "复核上下游图纸的标高链路，统一数值和引注。",
        "spatial_consistency": "复核空间定位和尺寸基准，统一图间表达。",
        "material_semantic_consistency": "统一材料命名、代号和对应表述。",
        "index_reference": "复核索引号、目标图号和引用关系。",
        "node_host_binding": "补齐母图与节点的引用归属关系。",
    }
    return mapping.get(str(worker_kind or "").strip(), "请结合图纸证据进一步复核。")


def _normalize_anchors(payload: Any) -> list[dict[str, Any]]:
    anchors = payload if isinstance(payload, list) else []
    normalized: list[dict[str, Any]] = []
    for index, anchor in enumerate(anchors):
        if not isinstance(anchor, dict):
            continue
        item = dict(anchor)
        role = str(item.get("role") or "").strip()
        if not role:
            item["role"] = "source" if index == 0 else "reference"
        normalized.append(item)
    return normalized


def _build_location_text(
    *,
    assignment: Any,
    worker_result: Any,
    anchors: list[dict[str, Any]],
) -> str:
    evidence_bundle = dict(_read_field(worker_result, "evidence_bundle", {}) or {})
    evidence_items = list(evidence_bundle.get("evidence") or [])
    first_evidence = evidence_items[0] if evidence_items and isinstance(evidence_items[0], dict) else {}
    location = str(first_evidence.get("location") or "").strip()
    if location:
        return location
    if anchors:
        anchor_sheets = [str(item.get("sheet_no") or "").strip() for item in anchors if str(item.get("sheet_no") or "").strip()]
        if anchor_sheets:
            return " / ".join(anchor_sheets)
    task_title = str(_read_field(assignment, "task_title", "") or "").strip()
    if task_title:
        return task_title
    return str(_read_field(worker_result, "summary", "") or "未定位").strip() or "未定位"


def convert_markdown_and_evidence_to_final_issues(
    *,
    organizer_markdown: str,
    accepted_decisions: list[Any],
) -> list[FinalIssue]:
    markdown_blocks = _split_markdown_blocks(organizer_markdown)
    issues: list[FinalIssue] = []

    for index, accepted_decision in enumerate(accepted_decisions, start=1):
        assignment = _read_field(accepted_decision, "assignment")
        worker_result = _read_field(accepted_decision, "worker_result")
        final_review_decision = _read_field(accepted_decision, "final_review_decision")
        evidence_bundle = dict(_read_field(worker_result, "evidence_bundle", {}) or {})
        anchors = _normalize_anchors(evidence_bundle.get("anchors"))
        summary = str(_read_field(worker_result, "summary", "") or "").strip()
        worker_kind = str(_read_field(worker_result, "worker_kind", "") or "").strip()
        severity = str(
            evidence_bundle.get("severity")
            or _read_field(_read_field(worker_result, "meta", {}), "severity", "warning")
            or "warning"
        ).strip().lower()
        if severity not in {"error", "warning", "info"}:
            severity = "warning"
        review_round = int(
            evidence_bundle.get("review_round")
            or _read_field(_read_field(worker_result, "meta", {}), "review_round", 1)
            or 1
        )
        markdown_block = markdown_blocks[index - 1] if index - 1 < len(markdown_blocks) else f"## 问题 {index}\n- {summary}"

        issues.append(
            FinalIssue(
                issue_code=f"ISS-{index:03d}",
                title=summary or str(_read_field(assignment, "task_title", "") or "待补充标题").strip(),
                description=summary or markdown_block,
                severity=severity,  # type: ignore[arg-type]
                finding_type=_worker_kind_to_finding_type(worker_kind),  # type: ignore[arg-type]
                disposition="accepted",
                source_agent="organizer_agent",
                source_assignment_id=str(_read_field(assignment, "assignment_id", "") or "").strip(),
                source_sheet_no=str(_read_field(assignment, "source_sheet_no", "") or "").strip(),
                target_sheet_nos=list(_read_field(assignment, "target_sheet_nos", []) or []),
                location_text=_build_location_text(
                    assignment=assignment,
                    worker_result=worker_result,
                    anchors=anchors,
                ),
                recommendation=_worker_kind_to_recommendation(worker_kind),
                evidence_pack_id=str(
                    _read_field(final_review_decision, "evidence_pack_id", "")
                    or evidence_bundle.get("evidence_pack_id")
                    or "chief_review_pack"
                ).strip()
                or "chief_review_pack",
                anchors=anchors,
                confidence=float(_read_field(worker_result, "confidence", 0.0) or 0.0),
                review_round=max(1, review_round),
                organizer_markdown_block=markdown_block,
            )
        )

    return issues


__all__ = ["convert_markdown_and_evidence_to_final_issues"]
