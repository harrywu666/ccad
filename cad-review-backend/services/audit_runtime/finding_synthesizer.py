"""把副审结果合成为主审 Findings。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from services.audit_runtime.finding_schema import Finding
from services.audit_runtime.review_task_schema import WorkerResultCard


def _worker_kind_to_finding_type(worker_kind: str) -> str:
    mapping = {
        "elevation_consistency": "dim_mismatch",
        "spatial_consistency": "dim_mismatch",
        "material_semantic_consistency": "material_conflict",
        "index_reference": "index_conflict",
        "node_host_binding": "missing_ref",
    }
    return mapping.get(str(worker_kind or "").strip(), "unknown")


def _worker_kind_to_rule_id(worker_kind: str) -> str:
    mapping = {
        "elevation_consistency": "ELEV-001",
        "spatial_consistency": "SPACE-001",
        "material_semantic_consistency": "MAT-001",
        "index_reference": "IDX-001",
        "node_host_binding": "NODE-001",
    }
    return mapping.get(str(worker_kind or "").strip(), "CHIEF-001")


def _to_finding(result: WorkerResultCard) -> Finding:
    evidence = list(result.evidence or [])
    anchor = dict(evidence[0] if evidence else {})
    sheet_no = str(anchor.get("sheet_no") or result.meta.get("sheet_no") or "UNKNOWN").strip() or "UNKNOWN"
    location = str(anchor.get("location") or result.meta.get("location") or result.summary or "未定位").strip() or "未定位"
    rule_id = str(anchor.get("rule_id") or result.meta.get("rule_id") or _worker_kind_to_rule_id(result.worker_kind)).strip()
    severity = str(result.meta.get("severity") or "warning").strip().lower()
    if severity not in {"error", "warning", "info"}:
        severity = "warning"
    return Finding(
        sheet_no=sheet_no,
        location=location,
        rule_id=rule_id,
        finding_type=_worker_kind_to_finding_type(result.worker_kind),  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        status="confirmed",
        confidence=float(result.confidence),
        source_agent="chief_review_agent",
        evidence_pack_id=str(result.meta.get("evidence_pack_id") or "chief_review_pack").strip() or "chief_review_pack",
        review_round=max(1, int(result.meta.get("review_round") or 1)),
        triggered_by=result.hypothesis_id,
        description=result.summary,
        meta={
            "execution_mode": str(
                result.meta.get("skill_mode") or result.meta.get("execution_mode") or "worker_result"
            ).strip(),
            "skill_id": str(result.meta.get("skill_id") or "").strip(),
            "skill_path": str(result.meta.get("skill_path") or "").strip(),
            "skill_version": str(result.meta.get("skill_version") or "").strip(),
            "prompt_source": str(result.meta.get("prompt_source") or "").strip(),
            "compat_mode": str(result.meta.get("compat_mode") or "").strip(),
            "session_key": str(result.meta.get("session_key") or "").strip(),
            "evidence_selection_policy": str(result.meta.get("evidence_selection_policy") or "").strip(),
        },
    )


def _resolve_conflicting_group(items: list[WorkerResultCard]) -> Finding | None:
    confirmed = sorted(
        [item for item in items if str(item.status or "").strip().lower() == "confirmed"],
        key=lambda item: float(item.confidence),
        reverse=True,
    )
    conflicting = sorted(
        [
            item
            for item in items
            if str(item.status or "").strip().lower() in {"rejected", "dismissed"}
        ],
        key=lambda item: float(item.confidence),
        reverse=True,
    )
    if not confirmed or not conflicting:
        return None
    if float(confirmed[0].confidence) >= 0.9 and float(conflicting[0].confidence) <= 0.55:
        return _to_finding(confirmed[0])
    confirmed_avg = sum(float(item.confidence) for item in confirmed) / len(confirmed)
    conflicting_avg = sum(float(item.confidence) for item in conflicting) / len(conflicting)
    if (
        len(confirmed) >= len(conflicting)
        and confirmed_avg >= 0.86
        and conflicting_avg <= 0.58
        and float(confirmed[0].confidence) - float(conflicting[0].confidence) >= 0.2
    ):
        return _to_finding(confirmed[0])
    return None


def synthesize_findings(
    *,
    worker_results: list[WorkerResultCard],
) -> tuple[list[Finding], list[dict[str, Any]]]:
    grouped: dict[str, list[WorkerResultCard]] = defaultdict(list)
    for item in worker_results:
        grouped[item.hypothesis_id].append(item)

    findings: list[Finding] = []
    escalations: list[dict[str, Any]] = []

    for hypothesis_id, items in grouped.items():
        statuses = {str(item.status or "").strip().lower() for item in items}
        if "confirmed" in statuses and ("rejected" in statuses or "dismissed" in statuses):
            resolved = _resolve_conflicting_group(items)
            if resolved is not None:
                findings.append(resolved)
                continue
            escalations.append(
                {
                    "hypothesis_id": hypothesis_id,
                    "escalate_to_chief": True,
                    "reasons": sorted(statuses),
                }
            )
            continue

        for item in items:
            status = str(item.status or "").strip().lower()
            if item.escalate_to_chief or status in {"needs_review", "conflict"}:
                escalations.append(
                    {
                        "hypothesis_id": hypothesis_id,
                        "task_id": item.task_id,
                        "escalate_to_chief": True,
                        "reasons": [status or "needs_review"],
                    }
                )
                continue
            if status == "confirmed" and float(item.confidence) >= 0.8:
                findings.append(_to_finding(item))

    return findings, escalations


__all__ = ["synthesize_findings"]
