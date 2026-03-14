"""把布局 JSON 编译成四层审图中间表示（IR）。"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence


_SHEET_TOKEN_PATTERN = re.compile(r"[A-Za-z]{1,3}\s*[-.]?\s*\d{1,4}(?:\s*[-.]?\s*\d{1,3})?")


def _stable_id(prefix: str, *parts: object) -> str:
    raw = "|".join(str(part or "").strip() for part in parts)
    digest = hashlib.sha1(raw.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return f"{prefix}-{digest}"


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return []


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return {}


def _as_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _parse_numeric_text(value: Any) -> Optional[float]:
    text = str(value or "").strip()
    if not text:
        return None
    filtered = "".join(ch for ch in text if ch in "0123456789.+-")
    if not filtered:
        return None
    try:
        return float(filtered)
    except ValueError:
        return None


def _normalize_sheet_no(value: Any) -> str:
    raw = str(value or "").strip().upper()
    if not raw:
        return ""
    return re.sub(r"[\s\-_./\\()（）【】\[\]{}:：|]+", "", raw)


def _extract_sheet_tokens(value: Any) -> list[str]:
    text = str(value or "")
    if not text:
        return []
    tokens: list[str] = []
    for match in _SHEET_TOKEN_PATTERN.finditer(text):
        token = _normalize_sheet_no(match.group(0))
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def _bbox_from_point(point: Sequence[float], radius: float = 5.0) -> list[float]:
    if len(point) < 2:
        return [0.0, 0.0, 0.0, 0.0]
    x = _as_float(point[0]) or 0.0
    y = _as_float(point[1]) or 0.0
    return [x - radius, y - radius, x + radius, y + radius]


def _bbox_from_min_max(min_obj: Any, max_obj: Any) -> Optional[list[float]]:
    if not isinstance(min_obj, list) or not isinstance(max_obj, list):
        return None
    if len(min_obj) < 2 or len(max_obj) < 2:
        return None
    x0 = _as_float(min_obj[0])
    y0 = _as_float(min_obj[1])
    x1 = _as_float(max_obj[0])
    y1 = _as_float(max_obj[1])
    if x0 is None or y0 is None or x1 is None or y1 is None:
        return None
    return [x0, y0, x1, y1]


def _point_from_global_pct(global_pct: Any, layout_bbox: Sequence[float]) -> Optional[list[float]]:
    if not isinstance(global_pct, dict):
        return None
    if len(layout_bbox) < 4:
        return None

    x_pct = _as_float(global_pct.get("x"))
    y_pct = _as_float(global_pct.get("y"))
    if x_pct is None or y_pct is None:
        return None

    x0 = _as_float(layout_bbox[0])
    y0 = _as_float(layout_bbox[1])
    x1 = _as_float(layout_bbox[2])
    y1 = _as_float(layout_bbox[3])
    if x0 is None or y0 is None or x1 is None or y1 is None:
        return None
    if x1 == x0 or y1 == y0:
        return None

    x_ratio = max(0.0, min(100.0, x_pct)) / 100.0
    y_ratio = max(0.0, min(100.0, y_pct)) / 100.0
    # 与 coordinate_service 的 Y 轴定义保持一致：pct_y=0 顶部，pct_y=100 底部。
    return [
        x0 + (x1 - x0) * x_ratio,
        y0 + (y1 - y0) * (1.0 - y_ratio),
    ]


def _bbox_from_global_pct(
    global_pct: Any,
    layout_bbox: Sequence[float],
    *,
    radius: float = 5.0,
) -> Optional[list[float]]:
    point = _point_from_global_pct(global_pct, layout_bbox)
    if point is None:
        return None
    return _bbox_from_point(point, radius=radius)


def _infer_space_id(
    fragment: dict[str, Any],
    *,
    layout_name: str,
    sheet_no: str,
) -> str:
    frag_id = str(fragment.get("fragment_id") or "").strip()
    return _stable_id("SP", layout_name, sheet_no, frag_id or "layout")


def _iter_index_attr_values(index: dict[str, Any]) -> list[str]:
    values: list[str] = []
    attrs = index.get("attrs")
    if not isinstance(attrs, list):
        return values
    for item in attrs:
        if not isinstance(item, dict):
            continue
        value = str(item.get("value") or "").strip()
        if value:
            values.append(value)
    return values


def _build_candidate_bindings(
    *,
    source_entity_id: str,
    index_no: str,
    target_sheet: str,
    label: str,
    known_sheet_nos: set[str],
    attr_values: list[str],
) -> list[dict[str, Any]]:
    normalized_target = _normalize_sheet_no(target_sheet)
    known_map = {
        _normalize_sheet_no(item): str(item).strip()
        for item in sorted(known_sheet_nos)
        if str(item).strip()
    }
    token_sources = [index_no, target_sheet, label, *attr_values]
    tokens: list[str] = []
    for source in token_sources:
        for token in _extract_sheet_tokens(source):
            if token not in tokens:
                tokens.append(token)
    if normalized_target and normalized_target not in tokens:
        tokens.append(normalized_target)

    candidate_scores: dict[str, tuple[float, list[str], list[str]]] = {}
    for normalized_sheet_no, sheet_no in known_map.items():
        score = 0.0
        basis: list[str] = []
        matched_tokens: list[str] = []
        if normalized_target and normalized_sheet_no == normalized_target:
            score = max(score, 0.96)
            basis.append("target_sheet_exact")
            matched_tokens.append(normalized_target)
        for token in tokens:
            if token == normalized_sheet_no:
                score = max(score, 0.9)
                basis.append("token_exact")
                matched_tokens.append(token)
            elif (
                token
                and normalized_sheet_no
                and len(token) >= 4
                and len(normalized_sheet_no) >= 4
                and (
                token in normalized_sheet_no or normalized_sheet_no in token
                )
            ):
                score = max(score, 0.72)
                basis.append("token_partial")
                matched_tokens.append(token)
        if score <= 0.0:
            continue
        existed = candidate_scores.get(sheet_no)
        if existed and existed[0] >= score:
            continue
        candidate_scores[sheet_no] = (score, basis, matched_tokens)

    candidates = [
        {
            "candidate_id": _stable_id("CAND", source_entity_id, sheet_no, index_no, target_sheet),
            "sheet_no": sheet_no,
            "normalized_sheet_no": _normalize_sheet_no(sheet_no),
            "score": round(score, 4),
            "basis": sorted(set(basis)),
            "matched_tokens": sorted(set(matched_tokens)),
            "is_known_sheet": True,
        }
        for sheet_no, (score, basis, matched_tokens) in candidate_scores.items()
    ]
    candidates.sort(key=lambda item: (-float(item.get("score") or 0.0), str(item.get("sheet_no") or "")))

    if candidates:
        return candidates
    if target_sheet:
        return [
            {
                "candidate_id": _stable_id("CAND", source_entity_id, target_sheet, "raw"),
                "sheet_no": target_sheet,
                "normalized_sheet_no": normalized_target,
                "score": 0.35,
                "basis": ["raw_target_unverified"],
                "matched_tokens": [],
                "is_known_sheet": False,
            }
        ]
    return []


def _build_reference_from_index(
    index: dict[str, Any],
    *,
    logical_sheet_id: str,
    known_sheet_nos: set[str],
) -> dict[str, Any]:
    index_no = str(index.get("index_no") or "").strip()
    target_sheet = str(index.get("target_sheet") or "").strip()
    source_entity_id = str(index.get("id") or "").strip() or _stable_id(
        "IDX",
        index_no,
        target_sheet,
        json.dumps(index, ensure_ascii=False, sort_keys=True),
    )
    label = f"{index_no}/{target_sheet}" if target_sheet else index_no
    candidate_bindings = _build_candidate_bindings(
        source_entity_id=source_entity_id,
        index_no=index_no,
        target_sheet=target_sheet,
        label=label,
        known_sheet_nos=known_sheet_nos,
        attr_values=_iter_index_attr_values(index),
    )
    selected = candidate_bindings[0] if candidate_bindings else None
    selected_sheet_no = str(selected.get("sheet_no") or "").strip() if isinstance(selected, dict) else ""
    selected_confidence = float(selected.get("score") or 0.0) if isinstance(selected, dict) else 0.0
    target_missing = bool(selected_sheet_no) and selected_sheet_no not in known_sheet_nos
    ambiguity_flags: list[str] = []
    if len(candidate_bindings) >= 2:
        first_score = float(candidate_bindings[0].get("score") or 0.0)
        second_score = float(candidate_bindings[1].get("score") or 0.0)
        if abs(first_score - second_score) < 0.12:
            ambiguity_flags.append("multi_candidate_close_score")
    if not selected_sheet_no and target_sheet:
        ambiguity_flags.append("target_sheet_unresolved")
    if selected_confidence < 0.6:
        ambiguity_flags.append("low_confidence_binding")
    return {
        "ref_id": _stable_id("REF", source_entity_id, target_sheet, logical_sheet_id),
        "type": "detail_callout",
        "label": label,
        "source_object_id": source_entity_id,
        "target_sheet_no": selected_sheet_no or (target_sheet or None),
        "source_logical_sheet_id": logical_sheet_id,
        "target_missing": target_missing if selected_sheet_no else bool(target_sheet),
        "confidence": selected_confidence or 0.45,
        "basis": ["index_block"],
        "candidate_bindings": candidate_bindings,
        "selected_candidate_id": str(selected.get("candidate_id") or "") if isinstance(selected, dict) else None,
        "ambiguity_flags": ambiguity_flags,
        "needs_llm_disambiguation": bool(ambiguity_flags),
    }


def _infer_sheet_type(sheet_no: str, sheet_title: str) -> str:
    text = f"{sheet_no} {sheet_title}".upper()
    if any(token in text for token in ("CEILING", "天花", "吊顶")):
        return "ceiling_plan"
    if any(token in text for token in ("FLOOR", "地坪", "地面")):
        return "floor_finish_plan"
    if any(token in text for token in ("ELEV", "立面")):
        return "elevation"
    if any(token in text for token in ("SECTION", "剖面")):
        return "section"
    return "floor_plan"


def _build_company_profile(layout_payload: dict[str, Any]) -> dict[str, Any]:
    drawing = str(layout_payload.get("source_dwg") or "").strip()
    preferred_encoding = "GB18030" if any("\u4e00" <= ch <= "\u9fff" for ch in drawing) else "UTF-8"
    return {
        "company_profile_id": _stable_id("CP", drawing or "default"),
        "company_name": str(layout_payload.get("company_name") or "default_company"),
        "version": "2026-03",
        "layer_naming": {
            "convention": "mixed",
            "wall_patterns": ["A-WALL", "WALL", "墙", "QIANG"],
            "door_patterns": ["A-DOOR", "DOOR", "门", "MEN"],
            "ceiling_patterns": ["A-CLNG", "CEILING", "DINGBENG", "吊顶"],
        },
        "dimension_strategy": {
            "primary_source": "paper_space",
            "trust_override": True,
            "fallback": "model_space",
        },
        "layout_strategy": {
            "one_layout_multi_sheet": bool(layout_payload.get("is_multi_sheet_layout")),
            "title_block_detection": "heuristic",
        },
        "block_library": {
            "door_block_patterns": ["DOOR*", "门*", "M-*"],
            "node_ref_block_patterns": ["索引*", "DETAIL*", "REF*"],
        },
        "encoding": {
            "preferred": preferred_encoding,
            "shx_font_map": {
                "hztxt.shx": "Noto Sans CJK SC",
                "gbcbig.shx": "Noto Sans CJK SC",
            },
        },
        "known_issues": [],
        "created_from_samples": [drawing] if drawing else [],
        "confidence": 0.82,
    }


def _infer_insert_block_type(insert: dict[str, Any]) -> tuple[str, float]:
    inferred = str(insert.get("inferred_type") or "").strip()
    if inferred:
        return inferred, float(insert.get("inferred_type_confidence") or 0.7)
    name = str(insert.get("block_name") or "").upper()
    if "DOOR" in name or "门" in name:
        return "door", 0.84
    if "WINDOW" in name or "窗" in name:
        return "window", 0.8
    if "TITLE" in name or "图签" in name:
        return "title_block", 0.78
    return "unknown_insert", 0.55


def _build_block_semantic_profiles(raw_inserts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in raw_inserts:
        if not isinstance(item, dict):
            continue
        block_name = str(item.get("block_name") or "").strip()
        if not block_name:
            continue
        grouped.setdefault(block_name, []).append(item)

    profiles: list[dict[str, Any]] = []
    for block_name, instances in grouped.items():
        sample = instances[0]
        inferred_type, inferred_confidence = _infer_insert_block_type(sample)
        required_keys = {"MARK", "WIDTH", "HEIGHT"} if inferred_type == "door" else set()
        key_attributes: list[dict[str, Any]] = []
        for key in sorted({k for ins in instances for k in _as_dict(ins.get("attributes")).keys()}):
            role = str(_as_dict(_as_dict(sample.get("attributes")).get(key)).get("semantic_role") or "generic_attribute")
            key_attributes.append(
                {
                    "attr_name": key,
                    "role": role,
                    "required": key in required_keys,
                }
            )

        profiles.append(
            {
                "block_semantic_profile_id": _stable_id("BSP", block_name, inferred_type),
                "block_name": block_name,
                "inferred_type": inferred_type,
                "subtype_candidates": [],
                "key_attributes": key_attributes,
                "basis": {
                    "block_name_pattern": block_name,
                    "layer_pattern": str(sample.get("layer") or ""),
                    "geometry_hint": "bbox",
                },
                "confidence": round(min(0.98, max(0.45, inferred_confidence)), 2),
                "instance_count": len(instances),
            }
        )
    return profiles


def _build_drawing_register(
    *,
    project_id: str,
    project_name: str,
    document_id: str,
    logical_sheet_id: str,
    sheet_no: str,
    sheet_title: str,
    entries: list[dict[str, Any]],
) -> dict[str, Any]:
    normalized_entries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in entries:
        if not isinstance(item, dict):
            continue
        number = str(item.get("sheet_number") or item.get("sheet_no") or "").strip()
        if not number or number in seen:
            continue
        seen.add(number)
        normalized_entries.append(
            {
                "sheet_number": number,
                "title": str(item.get("title") or item.get("sheet_name") or "").strip() or number,
                "document_id": str(item.get("document_id") or document_id),
                "logical_sheet_id": str(item.get("logical_sheet_id") or _stable_id("LS", document_id, number)),
                "floor_or_level": str(item.get("floor_or_level") or ""),
                "sheet_type": str(item.get("sheet_type") or _infer_sheet_type(number, str(item.get("title") or ""))),
            }
        )

    if sheet_no and sheet_no not in seen:
        normalized_entries.append(
            {
                "sheet_number": sheet_no,
                "title": sheet_title or sheet_no,
                "document_id": document_id,
                "logical_sheet_id": logical_sheet_id,
                "floor_or_level": "",
                "sheet_type": _infer_sheet_type(sheet_no, sheet_title),
            }
        )

    return {
        "project_id": project_id,
        "project_name": project_name,
        "drawing_register": {
            "drawing_register_id": _stable_id("DR", project_id or "project"),
            "source_document_id": document_id,
            "source_table_id": _stable_id("TB", document_id, "drawing_register"),
            "entries": normalized_entries,
            "confidence": 0.86 if normalized_entries else 0.55,
        },
        "project": {
            "project_id": project_id,
            "project_name": project_name,
            "floor_levels": sorted(
                {
                    str(item.get("floor_or_level") or "").strip()
                    for item in normalized_entries
                    if str(item.get("floor_or_level") or "").strip()
                }
            ),
            "drawing_register_id": _stable_id("DR", project_id or "project"),
            "document_ids": sorted(
                {str(item.get("document_id") or "").strip() for item in normalized_entries if str(item.get("document_id") or "").strip()}
            ),
        },
    }


def _build_clear_height_chains(
    *,
    spaces: list[dict[str, Any]],
    text_evidence: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    chains: list[dict[str, Any]] = []
    degradation: list[dict[str, Any]] = []
    ffl_value = None
    fcl_value = None
    sfl_value = None
    for item in text_evidence:
        content = str(item.get("content") or "").upper()
        num = _parse_numeric_text(content)
        if num is None:
            continue
        if "FFL" in content and ffl_value is None:
            ffl_value = num
        elif "FCL" in content and fcl_value is None:
            fcl_value = num
        elif "SFL" in content and sfl_value is None:
            sfl_value = num

    for space in spaces:
        space_id = str(space.get("space_id") or "")
        name = str(space.get("name") or "")
        if ffl_value is not None and fcl_value is not None:
            clear_height = fcl_value - ffl_value
            status = "pass" if clear_height >= 2400 else "warning" if clear_height >= 2200 else "fail"
            confidence = 0.83 if sfl_value is not None else 0.76
        else:
            clear_height = None
            status = "unknown"
            confidence = 0.45
            degradation.append(
                {
                    "id": _stable_id("DG", space_id or name, "clear_height_unknown"),
                    "reason": "clear_height_chain_incomplete",
                    "severity": "medium",
                    "impacted_rules": ["clearance_violation"],
                }
            )
        chains.append(
            {
                "clear_height_chain_id": _stable_id("CHC", space_id, name),
                "space_id": space_id,
                "space_name": name,
                "FFL_mm": ffl_value,
                "FFL_evidence_id": None,
                "FCL_mm": fcl_value,
                "FCL_evidence_id": None,
                "SFL_mm": sfl_value,
                "SFL_evidence_id": None,
                "plenum_height_mm": (sfl_value - fcl_value) if sfl_value is not None and fcl_value is not None else None,
                "computed_clear_height_mm": clear_height,
                "required_min_mm": 2400,
                "status": status,
                "conflict_note": None if status in {"pass", "warning"} else "clear_height_data_incomplete",
                "confidence": round(confidence, 2),
            }
        )
    return chains, degradation


def _build_sanitization_logs(normalized_entities: list[dict[str, Any]]) -> list[dict[str, Any]]:
    logs: list[dict[str, Any]] = []
    for entity in normalized_entities:
        if not isinstance(entity, dict):
            continue
        source_id = str(entity.get("source_entity_id") or entity.get("id") or "")
        payload = json.dumps(entity, ensure_ascii=False, sort_keys=True)
        logs.append(
            {
                "entity_id": source_id,
                "original_geometry_hash": f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}",
                "cleaning_operations": [],
                "validity_score": 0.95,
                "geometry_modified": False,
                "sanitization_status": "pass",
            }
        )
    return logs


def _collect_encoding_evidence(raw_texts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    records: list[dict[str, Any]] = []
    fallbacks: list[dict[str, Any]] = []
    for item in raw_texts:
        if not isinstance(item, dict):
            continue
        encoding = _as_dict(item.get("encoding"))
        if not encoding:
            continue
        record = {
            "source_entity_id": str(item.get("id") or ""),
            "raw_bytes_hex": encoding.get("raw_bytes_hex"),
            "encoding_detected": encoding.get("encoding_detected"),
            "encoding_confidence": encoding.get("encoding_confidence"),
            "text_utf8": encoding.get("text_utf8"),
            "font_name": encoding.get("font_name"),
            "font_substitution": encoding.get("font_substitution"),
            "font_substitution_reason": encoding.get("font_substitution_reason"),
            "ocr_fallback": encoding.get("ocr_fallback"),
            "ocr_triggered": bool(encoding.get("ocr_triggered")),
        }
        records.append(record)
        if bool(record.get("ocr_triggered")):
            fallbacks.append(record)
    return records, fallbacks


def compile_layout_ir(
    layout_payload: dict[str, Any],
    *,
    source_json_path: str,
    known_sheet_nos: Iterable[str] | None = None,
    project_id: str | None = None,
    project_name: str | None = None,
    drawing_register_entries: Sequence[dict[str, Any]] | None = None,
    company_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """把单张 layout JSON 转成四层 IR。"""
    now = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    source_path = str(Path(source_json_path).expanduser())

    source_dwg = str(layout_payload.get("source_dwg") or "").strip()
    layout_name = str(layout_payload.get("layout_name") or "").strip() or "UNKNOWN_LAYOUT"
    sheet_no = str(layout_payload.get("sheet_no") or "").strip() or layout_name
    sheet_name = str(layout_payload.get("sheet_name") or "").strip() or layout_name
    scale = str(layout_payload.get("scale") or "").strip()
    project_id = str(project_id or layout_payload.get("project_id") or "").strip() or "PROJ-UNKNOWN"
    project_name = str(project_name or layout_payload.get("project_name") or "").strip() or "默认项目"

    document_id = _stable_id("DOC", source_dwg or source_path)
    layout_id = _stable_id("LAYOUT", document_id, layout_name)
    review_view_id = _stable_id("RV", layout_id, sheet_no)
    logical_sheet_id = _stable_id("LS", document_id, sheet_no, sheet_name)

    layout_page_range = _as_dict(layout_payload.get("layout_page_range"))
    layout_bbox = _bbox_from_min_max(layout_page_range.get("min"), layout_page_range.get("max")) or [
        0.0,
        0.0,
        841.0,
        594.0,
    ]

    raw_dimensions = _as_list(layout_payload.get("dimensions"))
    raw_indexes = _as_list(layout_payload.get("indexes"))
    raw_title_blocks = _as_list(layout_payload.get("title_blocks"))
    raw_materials = _as_list(layout_payload.get("materials"))
    raw_tables = _as_list(layout_payload.get("material_table"))
    raw_texts = _as_list(layout_payload.get("pseudo_texts")) + _as_list(layout_payload.get("detail_titles"))
    raw_inserts = _as_list(layout_payload.get("insert_entities"))
    raw_layers = _as_list(layout_payload.get("layers"))
    raw_viewports = _as_list(layout_payload.get("viewports"))
    raw_fragments = _as_list(layout_payload.get("layout_fragments"))
    raw_layer_state_snapshot = _as_dict(layout_payload.get("layer_state_snapshot"))
    raw_z_summary = _as_dict(layout_payload.get("z_range_summary"))
    raw_text_encoding = _as_list(layout_payload.get("text_encoding_evidence"))

    known_sheet_no_set = {str(item or "").strip() for item in (known_sheet_nos or []) if str(item or "").strip()}
    drawing_register_bundle = _build_drawing_register(
        project_id=project_id,
        project_name=project_name,
        document_id=document_id,
        logical_sheet_id=logical_sheet_id,
        sheet_no=sheet_no,
        sheet_title=sheet_name,
        entries=list(drawing_register_entries or []),
    )
    company_profile = company_profile if isinstance(company_profile, dict) else _build_company_profile(layout_payload)

    references = [
        _build_reference_from_index(
            _as_dict(index),
            logical_sheet_id=logical_sheet_id,
            known_sheet_nos=known_sheet_no_set,
        )
        for index in raw_indexes
        if isinstance(index, dict)
    ]
    candidate_relations = [
        {
            "relation_id": str(ref.get("ref_id") or ""),
            "relation_type": "detail_callout_binding",
            "source_object_id": str(ref.get("source_object_id") or ""),
            "raw_label": str(ref.get("label") or ""),
            "candidate_bindings": list(ref.get("candidate_bindings") or []),
            "selected_candidate_id": str(ref.get("selected_candidate_id") or "") or None,
            "needs_llm_disambiguation": bool(ref.get("needs_llm_disambiguation")),
            "ambiguity_flags": list(ref.get("ambiguity_flags") or []),
            "confidence": float(ref.get("confidence") or 0.0),
        }
        for ref in references
    ]

    dimension_evidence: list[dict[str, Any]] = []
    normalized_entities: list[dict[str, Any]] = []
    degradation_notices: list[dict[str, Any]] = []
    skipped_non_numeric_dimensions = 0

    for item in raw_dimensions:
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id") or "").strip() or _stable_id(
            "DIMRAW",
            sheet_no,
            json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
        display_raw = item.get("display_text")
        display_value = _as_float(item.get("value"))
        if display_value is None:
            display_value = _parse_numeric_text(display_raw)
        if display_value is None:
            skipped_non_numeric_dimensions += 1
            continue
        bbox_from_pct = _bbox_from_global_pct(item.get("global_pct"), layout_bbox, radius=8.0)
        text_position = item.get("text_position")
        bbox = (
            bbox_from_pct
            if isinstance(bbox_from_pct, list)
            else _bbox_from_point(text_position if isinstance(text_position, list) else [0.0, 0.0], radius=8.0)
        )
        location_basis = "global_pct_projection" if isinstance(bbox_from_pct, list) else "text_position_fallback"
        dimension_id = _stable_id("DIM", raw_id, sheet_no)
        evidence = {
            "dimension_id": dimension_id,
            "source_entity_id": raw_id,
            "source_space": str(item.get("source") or "model_space"),
            "dimension_type": "aligned",
            "display_text_raw": str(display_raw or ""),
            "display_value": display_value,
            "value_source": str(item.get("value_source") or "display_preferred"),
            "unit": "mm",
            "truth_role": "display_value_authoritative",
            "owner_review_view_id": review_view_id,
            "linked_geometry_entity_ids": [],
            "confidence": (
                0.96
                if str(item.get("value_source") or "") == "display_text"
                else (0.9 if str(item.get("value_source") or "") == "display_generated" else 0.82)
            ),
            "bbox_canonical": bbox,
            "location_basis": location_basis,
        }
        dimension_evidence.append(evidence)
        normalized_entities.append(
            {
                "id": dimension_id,
                "source_entity_id": raw_id,
                "entity_type": "dimension",
                "space": evidence["source_space"],
                "bbox": bbox,
                "source_entity_ids": [raw_id],
                "owner_layout_id": layout_id,
                "owner_review_view_id": review_view_id,
                "z_min": _as_float(item.get("z_min")) if _as_float(item.get("z_min")) is not None else 0.0,
                "z_max": _as_float(item.get("z_max")) if _as_float(item.get("z_max")) is not None else 0.0,
                "z_range_label": str(item.get("z_range_label") or "dimension_annotation"),
                "elevation_band": str(item.get("elevation_band") or "human_accessible"),
                "included_in_plan_extraction": bool(item.get("included_in_plan_extraction", True)),
                "z_ambiguous": bool(item.get("z_ambiguous")),
            }
        )

    if skipped_non_numeric_dimensions:
        degradation_notices.append(
            {
                "id": _stable_id("DG", source_path, "dimension_non_numeric_display_value"),
                "reason": "dimension_non_numeric_display_value",
                "severity": "low",
                "impacted_rules": ["annotation_missing", "clearance_violation"],
                "count": skipped_non_numeric_dimensions,
            }
        )

    if not dimension_evidence:
        degradation_notices.append(
            {
                "id": _stable_id("DG", source_path, "missing_dimension"),
                "reason": "missing_dimension_evidence",
                "severity": "medium",
                "impacted_rules": ["annotation_missing", "clearance_violation"],
            }
        )

    if any(bool(ref.get("target_missing")) for ref in references):
        degradation_notices.append(
            {
                "id": _stable_id("DG", source_path, "missing_reference_target"),
                "reason": "reference_target_missing",
                "severity": "low",
                "impacted_rules": ["reference_broken", "cross_sheet_inconsistency"],
            }
        )

    if int(raw_z_summary.get("ambiguous_count") or 0) > 0:
        degradation_notices.append(
            {
                "id": _stable_id("DG", source_path, "z_axis_ambiguous"),
                "reason": "z_axis_ambiguous",
                "severity": "medium",
                "impacted_rules": ["space_boundary", "clearance_violation"],
            }
        )

    text_evidence: list[dict[str, Any]] = []
    for item in raw_texts:
        if not isinstance(item, dict):
            continue
        source_entity_id = str(item.get("id") or "").strip() or _stable_id(
            "TXTRAW",
            sheet_no,
            json.dumps(item, ensure_ascii=False, sort_keys=True),
        )
        content = str(item.get("text") or item.get("content") or "").strip()
        position = item.get("position")
        if not isinstance(position, list) or len(position) < 2:
            position = [0.0, 0.0]
        point_from_pct = _point_from_global_pct(item.get("global_pct"), layout_bbox)
        bbox_from_pct = _bbox_from_global_pct(item.get("global_pct"), layout_bbox, radius=6.0)
        bbox = bbox_from_pct if isinstance(bbox_from_pct, list) else _bbox_from_point(position, radius=6.0)
        text_position = (
            [(_as_float(point_from_pct[0]) or 0.0), (_as_float(point_from_pct[1]) or 0.0)]
            if isinstance(point_from_pct, list)
            else [(_as_float(position[0]) or 0.0), (_as_float(position[1]) or 0.0)]
        )
        location_basis = "global_pct_projection" if isinstance(bbox_from_pct, list) else "position_fallback"
        text_id = _stable_id("TXT", source_entity_id, sheet_no)
        text_evidence.append(
            {
                "text_id": text_id,
                "source_entity_id": source_entity_id,
                "space": "paper_space",
                "text_type_candidates": ["annotation"],
                "content": content,
                "position": text_position,
                "bbox": bbox,
                "rotation_deg": _as_float(item.get("rotation")) or 0.0,
                "owner_review_view_id": review_view_id,
                "confidence": 0.8 if content else 0.5,
                "location_basis": location_basis,
            }
        )
        normalized_entities.append(
            {
                "id": text_id,
                "source_entity_id": source_entity_id,
                "entity_type": "text",
                "space": str(item.get("source") or "paper_space"),
                "bbox": bbox,
                "source_entity_ids": [source_entity_id],
                "owner_layout_id": layout_id,
                "owner_review_view_id": review_view_id,
                "z_min": _as_float(item.get("z_min")) if _as_float(item.get("z_min")) is not None else 0.0,
                "z_max": _as_float(item.get("z_max")) if _as_float(item.get("z_max")) is not None else 0.0,
                "z_range_label": str(item.get("z_range_label") or "annotation_text"),
                "elevation_band": str(item.get("elevation_band") or "human_accessible"),
                "included_in_plan_extraction": bool(item.get("included_in_plan_extraction", True)),
                "z_ambiguous": bool(item.get("z_ambiguous")),
                "location_basis": location_basis,
            }
        )

    encoding_evidence, ocr_fallbacks = _collect_encoding_evidence(raw_texts)
    if not encoding_evidence and raw_text_encoding:
        encoding_evidence = [item for item in raw_text_encoding if isinstance(item, dict)]
        ocr_fallbacks = [item for item in encoding_evidence if bool(item.get("ocr_triggered"))]
    if ocr_fallbacks:
        degradation_notices.append(
            {
                "id": _stable_id("DG", source_path, "ocr_fallback_triggered"),
                "reason": "text_encoding_fallback_to_ocr",
                "severity": "low",
                "impacted_rules": ["annotation_missing", "reference_broken"],
            }
        )

    spaces: list[dict[str, Any]] = []
    fragments = [frag for frag in raw_fragments if isinstance(frag, dict)] or [{}]
    register_entries = _as_list(_as_dict(drawing_register_bundle.get("drawing_register")).get("entries"))
    for fragment in fragments:
        frag_bbox_obj = _as_dict(fragment.get("fragment_bbox"))
        frag_bbox = _bbox_from_min_max(frag_bbox_obj.get("min"), frag_bbox_obj.get("max")) or layout_bbox
        space_id = _infer_space_id(fragment, layout_name=layout_name, sheet_no=sheet_no)
        spaces.append(
            {
                "space_id": space_id,
                "name": str(fragment.get("sheet_name") or sheet_name),
                "boundary": {
                    "coordinate_space": "canonical_review",
                    "polygon": [
                        [frag_bbox[0], frag_bbox[1]],
                        [frag_bbox[2], frag_bbox[1]],
                        [frag_bbox[2], frag_bbox[3]],
                        [frag_bbox[0], frag_bbox[3]],
                    ],
                },
                "center": [
                    (frag_bbox[0] + frag_bbox[2]) / 2.0,
                    (frag_bbox[1] + frag_bbox[3]) / 2.0,
                ],
                "related_logical_sheet_ids": [logical_sheet_id],
                "cross_document_refs": [
                    {
                        "document_id": str(item.get("document_id") or document_id),
                        "logical_sheet_id": str(item.get("logical_sheet_id") or ""),
                        "local_space_id": _stable_id("SP", str(item.get("sheet_number") or ""), space_id),
                        "sheet_type": str(item.get("sheet_type") or "unknown"),
                    }
                    for item in register_entries[:6]
                    if isinstance(item, dict)
                ],
                "alignment_basis": ["name_match", "sheet_register"],
                "source_entity_ids": [],
                "confidence": 0.75,
            }
        )
    clear_height_chains, clear_height_degradation = _build_clear_height_chains(
        spaces=spaces,
        text_evidence=text_evidence,
    )
    degradation_notices.extend(clear_height_degradation)

    elements: list[dict[str, Any]] = []
    for material in raw_materials:
        if not isinstance(material, dict):
            continue
        element_id = _stable_id("EL", sheet_no, json.dumps(material, ensure_ascii=False, sort_keys=True))
        elements.append(
            {
                "element_id": element_id,
                "category": "finish_tag",
                "space_id": spaces[0]["space_id"] if spaces else None,
                "material_code": str(material.get("code") or material.get("material_code") or "").strip() or None,
                "description": str(material.get("description") or "").strip() or None,
                "source_entity_ids": [str(material.get("id") or element_id)],
                "confidence": 0.7,
            }
        )

    block_semantic_profiles = _build_block_semantic_profiles(
        [item for item in raw_inserts if isinstance(item, dict)]
    )
    for insert in raw_inserts:
        if not isinstance(insert, dict):
            continue
        source_insert_id = str(insert.get("id") or "").strip() or _stable_id(
            "INSRAW",
            sheet_no,
            json.dumps(insert, ensure_ascii=False, sort_keys=True),
        )
        insert_entity_id = _stable_id("INS", source_insert_id, sheet_no)
        effective_geometry = _as_dict(insert.get("effective_geometry"))
        bbox_obj = effective_geometry.get("bbox")
        bbox_from_pct = _bbox_from_global_pct(insert.get("global_pct"), layout_bbox, radius=6.0)
        fallback_bbox = (
            bbox_obj
            if isinstance(bbox_obj, list) and len(bbox_obj) >= 4
            else _bbox_from_point(
                insert.get("position") if isinstance(insert.get("position"), list) else [0.0, 0.0],
                radius=6.0,
            )
        )
        bbox = bbox_from_pct if isinstance(bbox_from_pct, list) else fallback_bbox
        location_basis = "global_pct_projection" if isinstance(bbox_from_pct, list) else "geometry_fallback"
        normalized_entities.append(
            {
                "id": insert_entity_id,
                "source_entity_id": source_insert_id,
                "entity_type": "insert",
                "space": str(insert.get("source") or "model_space"),
                "bbox": bbox,
                "source_entity_ids": [source_insert_id],
                "owner_layout_id": layout_id,
                "owner_review_view_id": review_view_id,
                "z_min": _as_float(insert.get("z_min")) if _as_float(insert.get("z_min")) is not None else 0.0,
                "z_max": _as_float(insert.get("z_max")) if _as_float(insert.get("z_max")) is not None else 0.0,
                "z_range_label": str(insert.get("z_range_label") or "unknown"),
                "elevation_band": str(insert.get("elevation_band") or "human_accessible"),
                "included_in_plan_extraction": bool(insert.get("included_in_plan_extraction", True)),
                "z_ambiguous": bool(insert.get("z_ambiguous")),
                "location_basis": location_basis,
            }
        )
        if bool(insert.get("is_dynamic_block")) and not bool(effective_geometry.get("resolved")):
            degradation_notices.append(
                {
                    "id": _stable_id("DG", source_insert_id, "dynamic_block_not_resolved"),
                    "reason": "dynamic_block_not_resolved",
                    "severity": "medium",
                    "impacted_rules": ["schedule_mismatch", "clearance_violation"],
                }
            )
        inferred_type = str(insert.get("inferred_type") or "unknown_insert")
        if inferred_type not in {"door", "window"}:
            continue
        element_id = _stable_id("EL", sheet_no, str(insert.get("id") or ""), inferred_type)
        resolved = bool(effective_geometry.get("resolved"))
        width = _as_float(_as_dict(insert.get("dynamic_params")).get("width_stretch_mm"))
        elements.append(
            {
                "element_id": element_id,
                "category": inferred_type,
                "space_id": spaces[0]["space_id"] if spaces else None,
                "material_code": None,
                "description": str(insert.get("block_name") or inferred_type),
                "width_mm": width,
                "width_confidence": 0.82 if resolved else 0.45,
                "width_degraded_reason": (
                    "dynamic_block_not_resolved_using_definition_default" if not resolved else None
                ),
                "source_entity_ids": [str(insert.get("id") or element_id)],
                "confidence": 0.8 if resolved else 0.5,
            }
        )

    tables: list[dict[str, Any]] = []
    if raw_tables:
        table_id = _stable_id("TB", sheet_no, "material_table")
        tables.append(
            {
                "table_id": table_id,
                "table_type": "material_schedule",
                "source_space": "paper_space",
                "owner_review_view_id": review_view_id,
                "rows": raw_tables,
                "source_entity_ids": [],
            }
        )

    sanitization_logs = _build_sanitization_logs(normalized_entities)
    layer_state_snapshots = [raw_layer_state_snapshot] if raw_layer_state_snapshot else []

    raw_layer = {
        "document": {
            "document_id": document_id,
            "source_path": source_dwg or source_path,
            "unit": "mm",
            "document_title": sheet_name,
            "parse_time": now,
            "parser": {
                "engine": "dxf_pipeline",
                "engine_mode": "program_first",
                "capability_matrix": {
                    "dynamic_block": "partial",
                    "viewport_clip_boundary": "partial",
                    "text_encoding_detection": "partial",
                    "z_axis_filtering": "partial",
                },
                "warnings": [],
            },
        },
        "layouts": [
            {
                "layout_id": layout_id,
                "name": layout_name,
                "space_type": "paper_space",
                "paper_bbox": layout_bbox,
                "scale": scale,
            }
        ],
        "viewports": raw_viewports,
        "layers": raw_layers,
        "layer_state_snapshot": raw_layer_state_snapshot,
        "drawing_register_entry": _as_dict(layout_payload.get("drawing_register_entry")),
        "company_profile_hint": company_profile,
        "raw_entities": {
            "dimensions": raw_dimensions,
            "inserts": raw_inserts,
            "indexes": raw_indexes,
            "title_blocks": raw_title_blocks,
            "materials": raw_materials,
            "tables": raw_tables,
            "texts": raw_texts,
            "text_encoding_evidence": raw_text_encoding,
        },
    }

    normalized_layer = {
        "normalized_entities": normalized_entities,
        "tolerance_registry": {
            "geom_merge_mm": 2.0,
            "dimension_value_mm": 1.0,
            "snap_grid_mm": 0.01,
            "micro_segment_mm": 0.01,
        },
        "z_range_summary": {
            "z_min": _as_float(raw_z_summary.get("z_min")) if _as_float(raw_z_summary.get("z_min")) is not None else 0.0,
            "z_max": _as_float(raw_z_summary.get("z_max")) if _as_float(raw_z_summary.get("z_max")) is not None else 0.0,
            "ambiguous_count": int(raw_z_summary.get("ambiguous_count") or 0),
            "sample_count": int(raw_z_summary.get("sample_count") or 0),
        },
        "layer_state_snapshots": layer_state_snapshots,
        "sanitization_logs": sanitization_logs,
        "transforms": [
            {
                "transform_id": _stable_id("TF", layout_id, review_view_id),
                "from_space": "paper_space",
                "to_space": "canonical_review",
                "layout_id": layout_id,
                "review_view_id": review_view_id,
                "scale": 1.0,
                "rotation_deg": 0.0,
                "translation": [0.0, 0.0],
                "confidence": 1.0,
            }
        ],
    }

    semantic_layer = {
        "review_views": [
            {
                "review_view_id": review_view_id,
                "layout_id": layout_id,
                "bbox_in_paper": layout_bbox,
                "sheet_number_candidates": [sheet_no],
                "title_candidates": [sheet_name],
                "sheet_type_candidates": [],
                "confidence": 0.9,
            }
        ],
        "logical_sheets": [
            {
                "logical_sheet_id": logical_sheet_id,
                "review_view_ids": [review_view_id],
                "sheet_number": sheet_no,
                "sheet_title": sheet_name,
                "confidence": 0.92,
            }
        ],
        "spaces": spaces,
        "elements": elements,
        "tables": tables,
        "block_semantic_profiles": block_semantic_profiles,
        "clear_height_chains": clear_height_chains,
        "elevation_views": [],
        "elevation_zones": [],
        "elevation_elements": [],
        "layer_state_snapshots": layer_state_snapshots,
        "references": references,
        "candidate_relations": candidate_relations,
    }

    evidence_layer = {
        "dimension_evidence": dimension_evidence,
        "text_evidence": text_evidence,
        "encoding_evidence": encoding_evidence,
        "ocr_fallbacks": ocr_fallbacks,
        "sanitization_logs": sanitization_logs,
        "layer_state_snapshots": layer_state_snapshots,
        "z_axis_evidence": {
            "z_min": _as_float(raw_z_summary.get("z_min")) if _as_float(raw_z_summary.get("z_min")) is not None else 0.0,
            "z_max": _as_float(raw_z_summary.get("z_max")) if _as_float(raw_z_summary.get("z_max")) is not None else 0.0,
            "ambiguous_count": int(raw_z_summary.get("ambiguous_count") or 0),
            "sample_count": int(raw_z_summary.get("sample_count") or 0),
        },
        "degradation_notices": degradation_notices,
        "ambiguity_flags": [
            {
                "ref_id": str(ref.get("ref_id") or ""),
                "flags": list(ref.get("ambiguity_flags") or []),
            }
            for ref in references
            if list(ref.get("ambiguity_flags") or [])
        ],
    }

    return {
        "schema_name": "dwg_to_json_core",
        "schema_version": "1.2.0",
        "compatible_with": ["1.1.x"],
        "generated_at": now,
        "source_json_path": source_path,
        "project": drawing_register_bundle.get("project"),
        "drawing_register": drawing_register_bundle.get("drawing_register"),
        "company_parsing_profile": company_profile,
        "raw_layer": raw_layer,
        "normalized_layer": normalized_layer,
        "semantic_layer": semantic_layer,
        "evidence_layer": evidence_layer,
    }


def persist_layout_ir(ir_package: dict[str, Any], *, source_json_path: str) -> str:
    json_path = Path(source_json_path).expanduser().resolve()
    ir_path = json_path.with_suffix(".ir.json")
    ir_path.write_text(json.dumps(ir_package, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(ir_path)
