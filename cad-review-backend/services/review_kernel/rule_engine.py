"""基于四层 IR 的规则执行器。"""

from __future__ import annotations

import hashlib
import re
from typing import Any

from domain.sheet_normalization import normalize_index_no, normalize_sheet_no


_DOC_SHEET_KEYWORDS = (
    "图纸封面",
    "图纸目录",
    "图纸说明",
    "设计说明",
    "材料表",
    "目录",
    "封面",
)
_MATERIAL_CODE_PATTERN = re.compile(r"[A-Z]{1,5}[-_]?\d{2,6}[A-Z]?")


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return f"{prefix}-{digest}"


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


def _build_sheet_location(
    *,
    logical_sheet_id: str,
    logical_sheet_title: Any,
    review_view_id: str,
    document_id: str,
    sheet_no: str,
    center_canonical: Any = None,
    bbox_canonical: Any = None,
) -> dict[str, Any]:
    return {
        "logical_sheet_id": logical_sheet_id,
        "logical_sheet_title": logical_sheet_title,
        "review_view_id": review_view_id,
        "document_id": document_id or None,
        "sheet_no": sheet_no or None,
        "bbox_canonical": bbox_canonical,
        "center_canonical": center_canonical,
    }


def _is_document_sheet(sheet_no: str, sheet_title: str) -> bool:
    merged = f"{sheet_no} {sheet_title}".strip()
    if any(keyword in merged for keyword in _DOC_SHEET_KEYWORDS):
        return True
    normalized_sheet_no = str(sheet_no or "").upper().replace(" ", "")
    if normalized_sheet_no.startswith("DL."):
        return True
    if normalized_sheet_no.startswith("DL"):
        return True
    return False


def _normalize_material_code(value: Any) -> str:
    code = str(value or "").strip().upper()
    if not code:
        return ""
    if not _MATERIAL_CODE_PATTERN.fullmatch(code):
        return ""
    return code


def _as_bbox(value: Any) -> list[float] | None:
    if not isinstance(value, list) or len(value) < 4:
        return None
    try:
        x1 = float(value[0])
        y1 = float(value[1])
        x2 = float(value[2])
        y2 = float(value[3])
    except (TypeError, ValueError):
        return None
    left, right = sorted((x1, x2))
    bottom, top = sorted((y1, y2))
    if right <= left or top <= bottom:
        return None
    return [left, bottom, right, top]


def _center_from_bbox(bbox: list[float] | None) -> list[float] | None:
    if not bbox:
        return None
    return [
        (float(bbox[0]) + float(bbox[2])) / 2.0,
        (float(bbox[1]) + float(bbox[3])) / 2.0,
    ]


def _extract_index_tokens_from_reference(ref: dict[str, Any]) -> list[str]:
    candidates = [
        str(ref.get("label") or "").strip(),
        str(ref.get("raw_label") or "").strip(),
    ]
    tokens: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not candidate:
            continue
        for seg in re.split(r"[/／\\|]", candidate):
            token = normalize_index_no(seg)
            if not token or token in seen:
                continue
            seen.add(token)
            tokens.append(token)
    return tokens


def _collect_target_detail_labels(ir_package: dict[str, Any]) -> set[str]:
    raw_layer = ir_package.get("raw_layer") if isinstance(ir_package.get("raw_layer"), dict) else {}
    raw_entities = raw_layer.get("raw_entities") if isinstance(raw_layer.get("raw_entities"), dict) else {}
    detail_titles = raw_entities.get("detail_titles") if isinstance(raw_entities.get("detail_titles"), list) else []
    indexes = raw_entities.get("indexes") if isinstance(raw_entities.get("indexes"), list) else []

    labels: set[str] = set()
    for item in detail_titles:
        if not isinstance(item, dict):
            continue
        token = normalize_index_no(str(item.get("label") or ""))
        if token:
            labels.add(token)

    for item in indexes:
        if not isinstance(item, dict):
            continue
        is_same_sheet = bool(item.get("same_sheet"))
        target_sheet = str(item.get("target_sheet") or "").strip()
        if not is_same_sheet and target_sheet:
            continue
        token = normalize_index_no(str(item.get("index_no") or ""))
        if token:
            labels.add(token)

    return labels


def _source_bbox_by_entity_id(ir_package: dict[str, Any]) -> dict[str, list[float]]:
    normalized_layer = ir_package.get("normalized_layer") if isinstance(ir_package.get("normalized_layer"), dict) else {}
    entities = normalized_layer.get("normalized_entities") if isinstance(normalized_layer.get("normalized_entities"), list) else []
    mapping: dict[str, list[float]] = {}
    for item in entities:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_entity_id") or "").strip()
        if not source_id or source_id in mapping:
            continue
        bbox = _as_bbox(item.get("bbox"))
        if bbox:
            mapping[source_id] = bbox
    return mapping


def run_review_rules(
    ir_package: dict[str, Any],
    context_slices: list[dict[str, Any]],
    *,
    material_code_coverage_threshold: float = 0.3,
) -> list[dict[str, Any]]:
    semantic = ir_package.get("semantic_layer") if isinstance(ir_package.get("semantic_layer"), dict) else {}
    evidence_layer = ir_package.get("evidence_layer") if isinstance(ir_package.get("evidence_layer"), dict) else {}
    raw_layer = ir_package.get("raw_layer") if isinstance(ir_package.get("raw_layer"), dict) else {}
    document = raw_layer.get("document") if isinstance(raw_layer.get("document"), dict) else {}

    logical_sheets = semantic.get("logical_sheets") if isinstance(semantic.get("logical_sheets"), list) else []
    logical_sheet = logical_sheets[0] if logical_sheets else {}
    sheet_no = str(logical_sheet.get("sheet_number") or "")
    sheet_title = str(logical_sheet.get("sheet_title") or "")
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
    elements = semantic.get("elements") if isinstance(semantic.get("elements"), list) else []
    tables = semantic.get("tables") if isinstance(semantic.get("tables"), list) else []

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
                location=_build_sheet_location(
                    logical_sheet_id=logical_sheet_id,
                    logical_sheet_title=sheet_title,
                    review_view_id=review_view_id,
                    document_id=document_id,
                    sheet_no=sheet_no,
                ),
                confidence=float(ref.get("confidence") or 0.6),
            )
        )

    risky_references: list[dict[str, Any]] = []
    for ref in references:
        if not isinstance(ref, dict):
            continue
        confidence = float(ref.get("confidence") or 0.0)
        ambiguity_flags = [str(item) for item in (ref.get("ambiguity_flags") or []) if str(item)]
        if confidence < 0.65 or ambiguity_flags or bool(ref.get("needs_human_confirm")):
            risky_references.append(
                {
                    "ref_id": str(ref.get("ref_id") or ""),
                    "label": str(ref.get("label") or ""),
                    "target_sheet_no": str(ref.get("target_sheet_no") or ""),
                    "confidence": confidence,
                    "ambiguity_flags": ambiguity_flags,
                    "needs_human_confirm": bool(ref.get("needs_human_confirm")),
                }
            )
    if risky_references:
        sample_refs = [item["label"] or item["ref_id"] for item in risky_references[:8]]
        low_conf_count = sum(1 for item in risky_references if item.get("confidence", 0.0) < 0.65)
        ambiguity_count = sum(1 for item in risky_references if item.get("ambiguity_flags"))
        issues.append(
            _build_issue(
                issue_id=_stable_id("ISS", "reference_risky", logical_sheet_id, len(risky_references)),
                rule_id="R-REF-002",
                rule_name="跨图索引置信度核验",
                category="cross_sheet_inconsistency",
                severity="warning",
                title="跨图索引存在低置信或歧义",
                description=(
                    f"图纸 {sheet_no or logical_sheet_id} 的索引中有 {len(risky_references)} 处存在低置信或歧义，"
                    f"其中低置信 {low_conf_count} 处、歧义 {ambiguity_count} 处。"
                ),
                suggested_fix="优先核查这些索引的目标图号与图签信息，必要时做人工确认。",
                evidence={
                    "primary_object_id": logical_sheet_id,
                    "primary_object_type": "logical_sheet",
                    "risky_reference_count": len(risky_references),
                    "low_confidence_count": low_conf_count,
                    "ambiguity_count": ambiguity_count,
                    "sample_references": sample_refs,
                },
                location=_build_sheet_location(
                    logical_sheet_id=logical_sheet_id,
                    logical_sheet_title=sheet_title,
                    review_view_id=review_view_id,
                    document_id=document_id,
                    sheet_no=sheet_no,
                ),
                confidence=0.64,
            )
        )

    finish_tags = [
        item
        for item in elements
        if isinstance(item, dict) and str(item.get("category") or "").strip().lower() == "finish_tag"
    ]
    finish_tag_codes = sorted(
        {
            _normalize_material_code(item.get("material_code"))
            for item in finish_tags
        }
        - {""}
    )
    material_tables = [
        item
        for item in tables
        if isinstance(item, dict) and str(item.get("table_type") or "").strip().lower() == "material_schedule"
    ]

    table_code_name_map: dict[str, set[str]] = {}
    for table in material_tables:
        rows = table.get("rows")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = _normalize_material_code(row.get("code") or row.get("material_code"))
            if not code:
                continue
            name = str(row.get("name") or row.get("description") or "").strip()
            table_code_name_map.setdefault(code, set())
            if name:
                table_code_name_map[code].add(name)
    table_codes = sorted(table_code_name_map.keys())

    if finish_tag_codes:
        if not material_tables:
            if len(finish_tags) >= 12:
                issues.append(
                    _build_issue(
                        issue_id=_stable_id("ISS", "material_schedule_missing", logical_sheet_id, len(finish_tags)),
                        rule_id="R-MAT-001",
                        rule_name="材料表同页可追溯性核验",
                        category="material_missing",
                        severity="warning",
                        title="材料标注较多但未检测到同页材料表",
                        description=(
                            f"图纸 {sheet_no or logical_sheet_id} 检测到 {len(finish_tags)} 处材料标注，"
                            "但当前页没有提取到可用材料表。"
                        ),
                        suggested_fix="确认材料表所在页并补充关联，或检查材料表提取策略。",
                        evidence={
                            "primary_object_id": logical_sheet_id,
                            "primary_object_type": "logical_sheet",
                            "finish_tag_count": len(finish_tags),
                            "finish_tag_code_count": len(finish_tag_codes),
                        },
                        location=_build_sheet_location(
                            logical_sheet_id=logical_sheet_id,
                            logical_sheet_title=sheet_title,
                            review_view_id=review_view_id,
                            document_id=document_id,
                            sheet_no=sheet_no,
                        ),
                        confidence=0.62,
                    )
                )
        elif not table_codes:
            issues.append(
                _build_issue(
                    issue_id=_stable_id("ISS", "material_schedule_parse_low_quality", logical_sheet_id),
                    rule_id="R-MAT-002",
                    rule_name="材料表编码完整性核验",
                    category="material_missing",
                    severity="warning",
                    title="材料表已提取但未识别到有效编码",
                    description=(
                        f"图纸 {sheet_no or logical_sheet_id} 检测到材料表，但未识别到有效材料编码，"
                        "暂时无法与图中材料标注做一致性校核。"
                    ),
                    suggested_fix="检查材料表 OCR/结构化提取策略，确保 code 列被正确识别。",
                    evidence={
                        "primary_object_id": logical_sheet_id,
                        "primary_object_type": "logical_sheet",
                        "finish_tag_code_count": len(finish_tag_codes),
                        "table_code_count": 0,
                    },
                    location=_build_sheet_location(
                        logical_sheet_id=logical_sheet_id,
                        logical_sheet_title=sheet_title,
                        review_view_id=review_view_id,
                        document_id=document_id,
                        sheet_no=sheet_no,
                    ),
                    confidence=0.66,
                )
            )
        else:
            missing_codes = [code for code in finish_tag_codes if code not in table_codes]
            coverage = (len(finish_tag_codes) - len(missing_codes)) / max(1, len(finish_tag_codes))
            if coverage < material_code_coverage_threshold:
                issues.append(
                    _build_issue(
                        issue_id=_stable_id(
                            "ISS",
                            "material_code_coverage_low",
                            logical_sheet_id,
                            len(missing_codes),
                            round(coverage, 3),
                        ),
                        rule_id="R-MAT-003",
                        rule_name="材料编码一致性核验",
                        category="material_mismatch",
                        severity="error" if coverage < 0.1 and len(finish_tag_codes) >= 10 else "warning",
                        title="材料标注与材料表编码匹配率偏低",
                        description=(
                            f"图纸 {sheet_no or logical_sheet_id} 材料编码匹配率仅 {coverage:.1%}，"
                            f"{len(finish_tag_codes)} 个标注编码中有 {len(missing_codes)} 个未在材料表中找到。"
                        ),
                        suggested_fix="核查材料表编码是否完整，或检查标注编码命名是否与材料表一致。",
                        evidence={
                            "primary_object_id": logical_sheet_id,
                            "primary_object_type": "logical_sheet",
                            "finish_tag_code_count": len(finish_tag_codes),
                            "table_code_count": len(table_codes),
                            "coverage": round(coverage, 4),
                            "missing_codes_sample": missing_codes[:12],
                        },
                        location=_build_sheet_location(
                            logical_sheet_id=logical_sheet_id,
                            logical_sheet_title=sheet_title,
                            review_view_id=review_view_id,
                            document_id=document_id,
                            sheet_no=sheet_no,
                        ),
                        confidence=0.71,
                    )
                )

    conflicted_codes = sorted([code for code, names in table_code_name_map.items() if len(names) >= 2])
    if conflicted_codes:
        issues.append(
            _build_issue(
                issue_id=_stable_id("ISS", "material_table_duplicate_conflict", logical_sheet_id, len(conflicted_codes)),
                rule_id="R-MAT-004",
                rule_name="材料表编码冲突核验",
                category="material_mismatch",
                severity="warning",
                title="材料表中存在同编码多名称冲突",
                description=(
                    f"图纸 {sheet_no or logical_sheet_id} 的材料表中有 {len(conflicted_codes)} 个编码对应了多个名称。"
                ),
                suggested_fix="核查材料表是否存在重复行或编码录入错误，统一编码与名称映射。",
                evidence={
                    "primary_object_id": logical_sheet_id,
                    "primary_object_type": "logical_sheet",
                    "conflicted_code_count": len(conflicted_codes),
                    "conflicted_codes_sample": conflicted_codes[:12],
                },
                location=_build_sheet_location(
                    logical_sheet_id=logical_sheet_id,
                    logical_sheet_title=sheet_title,
                    review_view_id=review_view_id,
                    document_id=document_id,
                    sheet_no=sheet_no,
                ),
                confidence=0.67,
            )
        )

    if not dimension_evidence and context_slices and not _is_document_sheet(sheet_no, sheet_title):
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
                location=_build_sheet_location(
                    logical_sheet_id=logical_sheet_id,
                    logical_sheet_title=sheet_title,
                    review_view_id=review_view_id,
                    document_id=document_id,
                    sheet_no=sheet_no,
                ),
                confidence=0.7,
            )
        )

    return issues


def run_cross_sheet_consistency_rules(ir_packages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sheet_contexts: dict[str, dict[str, Any]] = {}
    for ir_package in ir_packages:
        if not isinstance(ir_package, dict):
            continue
        semantic = ir_package.get("semantic_layer") if isinstance(ir_package.get("semantic_layer"), dict) else {}
        raw_layer = ir_package.get("raw_layer") if isinstance(ir_package.get("raw_layer"), dict) else {}
        document = raw_layer.get("document") if isinstance(raw_layer.get("document"), dict) else {}
        logical_sheets = semantic.get("logical_sheets") if isinstance(semantic.get("logical_sheets"), list) else []
        logical_sheet = logical_sheets[0] if logical_sheets else {}
        sheet_no = str(logical_sheet.get("sheet_number") or "").strip()
        if not sheet_no:
            continue
        key = normalize_sheet_no(sheet_no)
        if not key:
            continue
        review_views = semantic.get("review_views") if isinstance(semantic.get("review_views"), list) else []
        review_view_id = str(review_views[0].get("review_view_id") or "") if review_views else ""
        sheet_contexts[key] = {
            "sheet_no": sheet_no,
            "logical_sheet_id": str(logical_sheet.get("logical_sheet_id") or ""),
            "sheet_title": str(logical_sheet.get("sheet_title") or ""),
            "document_id": str(document.get("document_id") or ""),
            "review_view_id": review_view_id,
            "references": semantic.get("references") if isinstance(semantic.get("references"), list) else [],
            "target_labels": _collect_target_detail_labels(ir_package),
            "source_bbox_map": _source_bbox_by_entity_id(ir_package),
        }

    issues: list[dict[str, Any]] = []
    for source in sheet_contexts.values():
        source_sheet_no = str(source.get("sheet_no") or "")
        source_sheet_id = str(source.get("logical_sheet_id") or "")
        source_title = str(source.get("sheet_title") or "")
        source_document_id = str(source.get("document_id") or "")
        source_review_view_id = str(source.get("review_view_id") or "")
        refs = source.get("references") if isinstance(source.get("references"), list) else []
        source_bbox_map = source.get("source_bbox_map") if isinstance(source.get("source_bbox_map"), dict) else {}
        for ref in refs:
            if not isinstance(ref, dict):
                continue
            if bool(ref.get("target_missing")):
                continue
            target_sheet_no = str(ref.get("target_sheet_no") or "").strip()
            if not target_sheet_no:
                continue
            target_key = normalize_sheet_no(target_sheet_no)
            target = sheet_contexts.get(target_key)
            if not target:
                continue

            ref_id = str(ref.get("ref_id") or "").strip()
            index_tokens = _extract_index_tokens_from_reference(ref)
            if not index_tokens:
                continue

            target_labels = target.get("target_labels") if isinstance(target.get("target_labels"), set) else set()
            matched = [token for token in index_tokens if token in target_labels]
            if matched:
                continue

            source_entity_id = str(ref.get("source_object_id") or "").strip()
            source_bbox = _as_bbox(source_bbox_map.get(source_entity_id))
            issues.append(
                _build_issue(
                    issue_id=_stable_id(
                        "ISS",
                        "cross_sheet_detail_number_mismatch",
                        source_sheet_id,
                        ref_id,
                        target_sheet_no,
                        ",".join(index_tokens),
                    ),
                    rule_id="R-REF-003",
                    rule_name="跨图详图编号一致性核验",
                    category="cross_sheet_inconsistency",
                    severity="warning",
                    title="跨图索引在目标图未找到对应详图编号",
                    description=(
                        f"图纸 {source_sheet_no or source_sheet_id} 的索引 {ref.get('label') or ref_id} "
                        f"指向 {target_sheet_no}，但目标图未识别到对应编号（期望 {', '.join(index_tokens[:3])}）。"
                    ),
                    suggested_fix="核对索引编号与目标图详图编号是否一致，必要时同步修正索引块或目标图详图标题。",
                    evidence={
                        "primary_object_id": ref_id or source_entity_id or source_sheet_id,
                        "primary_object_type": "detail_callout",
                        "reference_id": ref_id or None,
                        "source_object_id": source_entity_id or None,
                        "target_sheet_no": target_sheet_no,
                        "expected_index_tokens": index_tokens,
                        "target_detail_label_sample": sorted(list(target_labels))[:12],
                        "target_detail_label_count": len(target_labels),
                    },
                    location=_build_sheet_location(
                        logical_sheet_id=source_sheet_id,
                        logical_sheet_title=source_title,
                        review_view_id=source_review_view_id,
                        document_id=source_document_id,
                        sheet_no=source_sheet_no,
                        bbox_canonical=source_bbox,
                        center_canonical=_center_from_bbox(source_bbox),
                    ),
                    confidence=min(float(ref.get("confidence") or 0.62), 0.82),
                )
            )
    return issues
