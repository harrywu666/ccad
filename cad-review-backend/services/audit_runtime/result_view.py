"""审核结果视图与统计工具。"""

from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Tuple

from models import AuditResult
from services.audit_runtime.finding_schema import finding_from_audit_result


def normalize_index_description(description: str | None) -> str:
    text = (description or "").strip()
    if not text:
        return ""
    # 将“索引A1/索引6”这类位置标签归一，便于相似问题合并
    import re

    text = re.sub(r"中的索引[^\s，。]+", "中的索引*", text)
    text = re.sub(r"索引[\w\-.]+", "索引*", text)
    return text


def normalize_feedback_status(value: str | None) -> str:
    return "incorrect" if value == "incorrect" else "none"


def serialize_audit_result(item: AuditResult) -> Dict[str, Any]:
    finding = finding_from_audit_result(item)
    location = item.location.strip() if isinstance(item.location, str) else item.location
    feedback_status = normalize_feedback_status(item.feedback_status)
    return {
        "id": item.id,
        "project_id": item.project_id,
        "audit_version": item.audit_version,
        "type": item.type,
        "severity": item.severity,
        "sheet_no_a": item.sheet_no_a,
        "sheet_no_b": item.sheet_no_b,
        "location": location,
        "locations": [location] if location else [],
        "occurrence_count": 1,
        "value_a": item.value_a,
        "value_b": item.value_b,
        "rule_id": finding.rule_id,
        "finding_type": finding.finding_type,
        "finding_status": finding.status,
        "source_agent": finding.source_agent,
        "evidence_pack_id": finding.evidence_pack_id,
        "review_round": finding.review_round,
        "triggered_by": finding.triggered_by,
        "confidence": finding.confidence,
        "description": item.description,
        "evidence_json": item.evidence_json,
        "is_resolved": bool(item.is_resolved),
        "resolved_at": item.resolved_at,
        "feedback_status": feedback_status,
        "feedback_at": item.feedback_at if feedback_status == "incorrect" else None,
        "feedback_note": item.feedback_note if feedback_status == "incorrect" else None,
        "is_grouped": False,
        "group_id": None,
        "issue_ids": [item.id],
    }


def group_results_for_view(raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[Any, ...], List[Dict[str, Any]]] = {}
    for item in raw_items:
        if item.get("type") == "index":
            key = (
                "index",
                item.get("sheet_no_a") or "",
                item.get("sheet_no_b") or "",
                normalize_index_description(item.get("description")),
            )
        else:
            # 仅对索引问题做合并，其他类型保留单条
            key = ("single", item["id"])
        groups.setdefault(key, []).append(item)

    grouped: List[Dict[str, Any]] = []
    for key, entries in groups.items():
        if len(entries) == 1 and key[0] == "single":
            grouped.append(entries[0])
            continue

        first = entries[0]
        issue_ids = [entry["id"] for entry in entries]
        all_locations: List[str] = []
        for entry in entries:
            for loc in entry.get("locations") or []:
                if isinstance(loc, str) and loc and loc not in all_locations:
                    all_locations.append(loc)

        if not all_locations and first.get("location"):
            all_locations = [first["location"]]

        if len(all_locations) <= 4:
            location_text = "、".join(all_locations) if all_locations else first.get("location")
        else:
            location_text = f"{'、'.join(all_locations[:4])} 等{len(all_locations)}处"

        resolved_values = [bool(entry.get("is_resolved")) for entry in entries]
        is_resolved = all(resolved_values) if resolved_values else False
        resolved_candidates = [entry.get("resolved_at") for entry in entries if entry.get("resolved_at")]
        resolved_at = max(resolved_candidates) if (is_resolved and resolved_candidates) else None
        feedback_values = [normalize_feedback_status(entry.get("feedback_status")) for entry in entries]
        feedback_status = "incorrect" if any(value == "incorrect" for value in feedback_values) else "none"
        feedback_candidates = [entry.get("feedback_at") for entry in entries if entry.get("feedback_at")]
        feedback_at = max(feedback_candidates) if (feedback_status == "incorrect" and feedback_candidates) else None
        feedback_notes = [entry.get("feedback_note") for entry in entries if entry.get("feedback_note")]
        feedback_note = feedback_notes[0] if (feedback_status == "incorrect" and feedback_notes) else None

        key_text = "|".join(str(part) for part in key)
        group_id = f"group_{hashlib.md5(key_text.encode('utf-8')).hexdigest()[:16]}"

        grouped.append(
            {
                **first,
                "id": group_id,
                "location": location_text,
                "locations": all_locations,
                "occurrence_count": len(issue_ids),
                "is_resolved": is_resolved,
                "resolved_at": resolved_at,
                "feedback_status": feedback_status,
                "feedback_at": feedback_at,
                "feedback_note": feedback_note,
                "is_grouped": True,
                "group_id": group_id,
                "issue_ids": issue_ids,
            }
        )

    return grouped


def summarize_grouped_counts(grouped_items: List[Dict[str, Any]]) -> Dict[str, Any]:
    unresolved = {"index": 0, "dimension": 0, "material": 0}
    for item in grouped_items:
        if item.get("is_resolved"):
            continue
        issue_type = str(item.get("type") or "").strip()
        if issue_type in unresolved:
            unresolved[issue_type] += 1
    return {
        "total": len(grouped_items),
        "unresolved": unresolved,
    }

