"""Issue 约束策略：置信度传播与高严重度保护。"""

from __future__ import annotations

from typing import Any


_HIGH_SEVERITY = {"error", "critical", "high"}


def _index_dimension_evidence(ir_package: dict[str, Any]) -> dict[str, dict[str, Any]]:
    evidence_layer = ir_package.get("evidence_layer") if isinstance(ir_package.get("evidence_layer"), dict) else {}
    items = evidence_layer.get("dimension_evidence")
    if not isinstance(items, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        key = str(item.get("dimension_id") or "").strip()
        if key:
            result[key] = item
    return result


def _global_degradation_cap(ir_package: dict[str, Any]) -> float:
    evidence_layer = ir_package.get("evidence_layer") if isinstance(ir_package.get("evidence_layer"), dict) else {}
    notices = evidence_layer.get("degradation_notices")
    if not isinstance(notices, list):
        return 1.0
    cap = 1.0
    for item in notices:
        if not isinstance(item, dict):
            continue
        severity = str(item.get("severity") or "").strip().lower()
        if severity in {"critical", "high"}:
            cap = min(cap, 0.55)
        elif severity == "medium":
            cap = min(cap, 0.72)
        elif severity == "low":
            cap = min(cap, 0.86)
    return cap


def apply_confidence_propagation(
    issues: list[dict[str, Any]],
    ir_package: dict[str, Any],
) -> list[dict[str, Any]]:
    dim_map = _index_dimension_evidence(ir_package)
    global_cap = _global_degradation_cap(ir_package)
    patched: list[dict[str, Any]] = []

    for issue in issues:
        if not isinstance(issue, dict):
            continue
        local_cap = 1.0
        evidence = issue.get("evidence")
        if isinstance(evidence, dict):
            dim_id = str(evidence.get("dimension_evidence_id") or "").strip()
            if dim_id and dim_id in dim_map:
                score = dim_map[dim_id].get("confidence")
                if isinstance(score, (int, float)):
                    local_cap = min(local_cap, float(score))
            if evidence.get("target_sheet_no") and evidence.get("basis") == []:
                local_cap = min(local_cap, 0.8)
        final_cap = min(local_cap, global_cap)
        current_confidence = float(issue.get("confidence") or 0.0)
        issue["confidence"] = min(current_confidence, final_cap)
        patched.append(issue)
    return patched


def enforce_high_severity_constraint(
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    patched: list[dict[str, Any]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        severity = str(issue.get("severity") or "").strip().lower()
        if severity not in _HIGH_SEVERITY:
            patched.append(issue)
            continue

        generated_by = str(issue.get("generated_by") or "").strip().lower()
        has_rule_id = bool(str(issue.get("rule_id") or "").strip())
        evidence = issue.get("evidence")
        has_structured_evidence = isinstance(evidence, dict) and bool(
            evidence.get("primary_object_id") or evidence.get("dimension_evidence_id")
        )

        if generated_by != "rule_engine" and (not has_rule_id or not has_structured_evidence):
            issue["severity"] = "warning"
            issue["reviewed_status"] = "needs_human_review"
            issue["high_severity_guard"] = "downgraded_missing_structured_support"
        elif not has_structured_evidence:
            issue["reviewed_status"] = "needs_human_review"
            issue["high_severity_guard"] = "queued_for_manual_review"
        patched.append(issue)
    return patched
