"""把四层 IR 切成可喂给规则和模型的小上下文块。"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _estimate_tokens(payload: dict[str, Any]) -> int:
    return max(1, int(len(json.dumps(payload, ensure_ascii=False)) / 4))


def _trim_to_budget(payload: dict[str, Any], max_tokens: int) -> dict[str, Any]:
    if _estimate_tokens(payload) <= max_tokens:
        return payload

    trimmed = dict(payload)
    for key in (
        "dimension_evidence",
        "references",
        "candidate_relations",
        "elements",
        "tables",
        "text_evidence",
        "encoding_evidence",
        "sanitization_logs",
        "block_semantic_profiles",
        "clear_height_chains",
        "elevation_views",
        "elevation_zones",
        "elevation_elements",
    ):
        value = trimmed.get(key)
        if not isinstance(value, list) or not value:
            continue
        half = max(1, len(value) // 2)
        trimmed[key] = value[:half]
        if _estimate_tokens(trimmed) <= max_tokens:
            return trimmed

    return {
        "logical_sheet": trimmed.get("logical_sheet"),
        "review_view": trimmed.get("review_view"),
        "rule_scope": trimmed.get("rule_scope"),
    }


def _first_list_item(obj: dict[str, Any], key: str) -> dict[str, Any]:
    value = obj.get(key)
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return value[0]
    return {}


def find_slice_by_type(
    slices: list[dict[str, Any]],
    slice_type: str,
) -> dict[str, Any] | None:
    for item in slices:
        if str(item.get("slice_type") or "").strip() == slice_type:
            return item
    return None


def build_context_slices(
    ir_package: dict[str, Any],
    *,
    max_slice_tokens: int = 8000,
) -> list[dict[str, Any]]:
    semantic = ir_package.get("semantic_layer") if isinstance(ir_package.get("semantic_layer"), dict) else {}
    evidence = ir_package.get("evidence_layer") if isinstance(ir_package.get("evidence_layer"), dict) else {}

    logical_sheet = _first_list_item(semantic, "logical_sheets")
    review_view = _first_list_item(semantic, "review_views")
    references = semantic.get("references") if isinstance(semantic.get("references"), list) else []
    candidate_relations = (
        semantic.get("candidate_relations")
        if isinstance(semantic.get("candidate_relations"), list)
        else []
    )
    spaces = semantic.get("spaces") if isinstance(semantic.get("spaces"), list) else []
    elements = semantic.get("elements") if isinstance(semantic.get("elements"), list) else []
    tables = semantic.get("tables") if isinstance(semantic.get("tables"), list) else []
    dimension_evidence = (
        evidence.get("dimension_evidence")
        if isinstance(evidence.get("dimension_evidence"), list)
        else []
    )
    encoding_evidence = (
        evidence.get("encoding_evidence")
        if isinstance(evidence.get("encoding_evidence"), list)
        else []
    )
    text_evidence = evidence.get("text_evidence") if isinstance(evidence.get("text_evidence"), list) else []
    sanitization_logs = (
        evidence.get("sanitization_logs")
        if isinstance(evidence.get("sanitization_logs"), list)
        else []
    )
    degradation_notices = (
        evidence.get("degradation_notices")
        if isinstance(evidence.get("degradation_notices"), list)
        else []
    )
    ambiguity_flags = (
        evidence.get("ambiguity_flags")
        if isinstance(evidence.get("ambiguity_flags"), list)
        else []
    )
    clear_height_chains = (
        semantic.get("clear_height_chains")
        if isinstance(semantic.get("clear_height_chains"), list)
        else []
    )
    block_semantic_profiles = (
        semantic.get("block_semantic_profiles")
        if isinstance(semantic.get("block_semantic_profiles"), list)
        else []
    )
    elevation_views = (
        semantic.get("elevation_views")
        if isinstance(semantic.get("elevation_views"), list)
        else []
    )
    elevation_zones = (
        semantic.get("elevation_zones")
        if isinstance(semantic.get("elevation_zones"), list)
        else []
    )
    elevation_elements = (
        semantic.get("elevation_elements")
        if isinstance(semantic.get("elevation_elements"), list)
        else []
    )

    if not spaces:
        spaces = [
            {
                "space_id": _stable_id(
                    "SP",
                    logical_sheet.get("logical_sheet_id"),
                    logical_sheet.get("sheet_number"),
                ),
                "name": str(logical_sheet.get("sheet_title") or logical_sheet.get("sheet_number") or "UNKNOWN"),
                "related_logical_sheet_ids": [logical_sheet.get("logical_sheet_id")],
            }
        ]

    slices: list[dict[str, Any]] = []
    for space in spaces:
        space_id = str(space.get("space_id") or "")
        payload = {
            "space": space,
            "logical_sheet": logical_sheet,
            "review_view": review_view,
            "elements": [item for item in elements if str(item.get("space_id") or "") in {"", space_id}],
            "tables": tables,
            "references": references,
            "dimension_evidence": dimension_evidence,
            "text_evidence": text_evidence,
            "encoding_evidence": encoding_evidence,
            "sanitization_logs": sanitization_logs,
            "degradation_notices": degradation_notices,
            "clear_height_chains": clear_height_chains,
            "block_semantic_profiles": block_semantic_profiles,
            "elevation_views": elevation_views,
            "elevation_zones": elevation_zones,
            "elevation_elements": elevation_elements,
            "rule_scope": ["dimension_conflict", "reference_broken", "annotation_missing"],
        }
        payload = _trim_to_budget(payload, max_slice_tokens)
        token_estimate = _estimate_tokens(payload)
        slices.append(
            {
                "context_slice_id": _stable_id("CS", logical_sheet.get("logical_sheet_id"), "space", space_id),
                "slice_type": "space_review",
                "target_space_id": space_id,
                "target_space_name": str(space.get("name") or ""),
                "applicable_rule_ids": ["R-DIM-001", "R-REF-001", "R-ANN-001"],
                "token_estimate": token_estimate,
                "payload": payload,
            }
        )

    relation_payload = {
        "logical_sheet": logical_sheet,
        "review_view": review_view,
        "candidate_relations": candidate_relations,
        "references": references,
        "dimension_evidence": dimension_evidence,
        "ambiguity_flags": ambiguity_flags,
        "degradation_notices": degradation_notices,
        "encoding_evidence": encoding_evidence,
        "rule_scope": ["reference_broken", "cross_sheet_inconsistency"],
    }
    relation_payload = _trim_to_budget(relation_payload, max_slice_tokens)
    slices.append(
        {
            "context_slice_id": _stable_id(
                "CS",
                logical_sheet.get("logical_sheet_id"),
                "relation_disambiguation",
            ),
            "slice_type": "relation_disambiguation",
            "target_space_id": None,
            "target_space_name": "",
            "applicable_rule_ids": ["R-REF-001"],
            "token_estimate": _estimate_tokens(relation_payload),
            "payload": relation_payload,
        }
    )
    return slices


def build_report_context_slice(
    ir_package: dict[str, Any],
    issues: list[dict[str, Any]],
    *,
    max_slice_tokens: int = 4000,
) -> dict[str, Any]:
    semantic = ir_package.get("semantic_layer") if isinstance(ir_package.get("semantic_layer"), dict) else {}
    evidence = ir_package.get("evidence_layer") if isinstance(ir_package.get("evidence_layer"), dict) else {}
    logical_sheet = _first_list_item(semantic, "logical_sheets")
    review_view = _first_list_item(semantic, "review_views")
    payload = {
        "logical_sheet": logical_sheet,
        "review_view": review_view,
        "issues": issues,
        "degradation_notices": (
            evidence.get("degradation_notices")
            if isinstance(evidence.get("degradation_notices"), list)
            else []
        ),
        "rule_scope": ["reporting"],
    }
    payload = _trim_to_budget(payload, max_slice_tokens)
    return {
        "context_slice_id": _stable_id("CS", logical_sheet.get("logical_sheet_id"), "report"),
        "slice_type": "report_writing",
        "token_estimate": _estimate_tokens(payload),
        "payload": payload,
    }
