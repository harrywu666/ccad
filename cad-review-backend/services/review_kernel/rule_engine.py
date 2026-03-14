"""基于四层 IR 的规则执行器。"""

from __future__ import annotations

import hashlib
from typing import Any, Optional


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_issue(
    *,
    issue_id: str,
    rule_id: str,
    rule_name: str,
    category: str,
    severity: str,
    title: str,
    description: str,
    suggested_fix: str,
    evidence: dict[str, Any],
    location: dict[str, Any],
    confidence: float,
) -> dict[str, Any]:
    return {
        "issue_id": issue_id,
        "rule_id": rule_id,
        "rule_name": rule_name,
        "category": category,
        "severity": severity,
        "title": title,
        "description": description,
        "suggested_fix": suggested_fix,
        "evidence": evidence,
        "location": location,
        "cross_sheet_refs": [],
        "confidence": confidence,
        "generated_by": "rule_engine",
        "deterministic_support": True,
        "reviewed_status": "open",
    }


def run_review_rules(
    ir_package: dict[str, Any],
    context_slices: list[dict[str, Any]],
    *,
    dimension_conflict_threshold_mm: float = 1.0,
) -> list[dict[str, Any]]:
    semantic = ir_package.get("semantic_layer") if isinstance(ir_package.get("semantic_layer"), dict) else {}
    evidence_layer = ir_package.get("evidence_layer") if isinstance(ir_package.get("evidence_layer"), dict) else {}
    raw_layer = ir_package.get("raw_layer") if isinstance(ir_package.get("raw_layer"), dict) else {}
    document = raw_layer.get("document") if isinstance(raw_layer.get("document"), dict) else {}

    logical_sheets = semantic.get("logical_sheets") if isinstance(semantic.get("logical_sheets"), list) else []
    logical_sheet = logical_sheets[0] if logical_sheets else {}
    sheet_no = str(logical_sheet.get("sheet_number") or "")
    logical_sheet_id = str(logical_sheet.get("logical_sheet_id") or "")
    document_id = str(document.get("document_id") or "")
    review_view_id = ""
    review_views = semantic.get("review_views")
    if isinstance(review_views, list) and review_views:
        review_view_id = str(review_views[0].get("review_view_id") or "")

    issues: list[dict[str, Any]] = []
    dimension_evidence = (
        evidence_layer.get("dimension_evidence")
        if isinstance(evidence_layer.get("dimension_evidence"), list)
        else []
    )
    references = semantic.get("references") if isinstance(semantic.get("references"), list) else []

    for dim in dimension_evidence:
        if not isinstance(dim, dict):
            continue
        display_value = _as_float(dim.get("display_value"))
        measured_value = _as_float(dim.get("measured_value"))
        if display_value is None or measured_value is None:
            continue
        delta = abs(display_value - measured_value)
        if delta <= dimension_conflict_threshold_mm:
            continue
        dim_id = str(dim.get("dimension_id") or "")
        issues.append(
            _build_issue(
                issue_id=_stable_id("ISS", "dimension_conflict", dim_id, delta),
                rule_id="R-DIM-001",
                rule_name="标注显示值与测量值一致性核验",
                category="dimension_conflict",
                severity="error",
                title="尺寸标注与测量值冲突",
                description=(
                    f"图纸 {sheet_no or logical_sheet_id} 中尺寸 {dim_id} 显示值 {display_value:.3f}mm，"
                    f"测量值 {measured_value:.3f}mm，差值 {delta:.3f}mm。"
                ),
                suggested_fix="核对尺寸是否手工改写；如为设计意图，请同步修正几何或补充说明。",
                evidence={
                    "primary_object_id": dim_id,
                    "primary_object_type": "dimension",
                    "display_value": display_value,
                    "measured_value": measured_value,
                    "delta_mm": delta,
                    "dimension_evidence_id": dim_id,
                    "source_space": dim.get("source_space"),
                    "is_override": bool(dim.get("is_override")),
                },
                location={
                    "logical_sheet_id": logical_sheet_id,
                    "logical_sheet_title": logical_sheet.get("sheet_title"),
                    "review_view_id": review_view_id,
                    "document_id": document_id or None,
                    "sheet_no": sheet_no or None,
                    "bbox_canonical": dim.get("bbox_canonical"),
                    "center_canonical": (
                        [
                            (float(dim.get("bbox_canonical")[0]) + float(dim.get("bbox_canonical")[2])) / 2.0,
                            (float(dim.get("bbox_canonical")[1]) + float(dim.get("bbox_canonical")[3])) / 2.0,
                        ]
                        if isinstance(dim.get("bbox_canonical"), list) and len(dim.get("bbox_canonical")) >= 4
                        else None
                    ),
                },
                confidence=min(float(dim.get("confidence") or 0.8), 0.95),
            )
        )

    for ref in references:
        if not isinstance(ref, dict):
            continue
        if not bool(ref.get("target_missing")):
            continue
        ref_id = str(ref.get("ref_id") or "")
        target_sheet = str(ref.get("target_sheet_no") or "")
        issues.append(
            _build_issue(
                issue_id=_stable_id("ISS", "reference_broken", ref_id, target_sheet),
                rule_id="R-REF-001",
                rule_name="索引引用有效性核验",
                category="reference_broken",
                severity="warning",
                title="索引引用目标图纸缺失",
                description=f"索引 {ref.get('label') or ref_id} 指向图纸 {target_sheet or '未知'}，但当前项目中未找到。",
                suggested_fix="补齐目标图纸，或修正索引中的目标图号。",
                evidence={
                    "primary_object_id": ref_id,
                    "primary_object_type": "detail_callout",
                    "target_sheet_no": target_sheet or None,
                    "basis": ref.get("basis") or [],
                },
                location={
                    "logical_sheet_id": logical_sheet_id,
                    "logical_sheet_title": logical_sheet.get("sheet_title"),
                    "review_view_id": review_view_id,
                    "document_id": document_id or None,
                    "sheet_no": sheet_no or None,
                    "center_canonical": None,
                },
                confidence=float(ref.get("confidence") or 0.6),
            )
        )

    if not dimension_evidence and context_slices:
        first_slice = context_slices[0]
        issues.append(
            _build_issue(
                issue_id=_stable_id("ISS", "annotation_missing", logical_sheet_id),
                rule_id="R-ANN-001",
                rule_name="关键标注存在性核验",
                category="annotation_missing",
                severity="warning",
                title="缺少可用尺寸证据",
                description=f"图纸 {sheet_no or logical_sheet_id} 没有提取到尺寸证据，部分规则无法执行。",
                suggested_fix="检查该图纸是否缺少尺寸标注，或解析配置是否漏掉图层/视口内容。",
                evidence={
                    "primary_object_id": str(first_slice.get("context_slice_id") or ""),
                    "primary_object_type": "context_slice",
                },
                location={
                    "logical_sheet_id": logical_sheet_id,
                    "logical_sheet_title": logical_sheet.get("sheet_title"),
                    "review_view_id": review_view_id,
                    "document_id": document_id or None,
                    "sheet_no": sheet_no or None,
                    "center_canonical": None,
                },
                confidence=0.7,
            )
        )

    return issues
