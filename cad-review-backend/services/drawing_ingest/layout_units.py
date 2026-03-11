from __future__ import annotations

from copy import deepcopy
import math
import re
from typing import Any, Dict, List


def _fragment_has_identity(fragment: Dict[str, Any]) -> bool:
    if str(fragment.get("sheet_no") or "").strip():
        return True
    if fragment.get("title_blocks"):
        return True
    if fragment.get("detail_titles"):
        return True
    return False


def _fragment_content_score(fragment: Dict[str, Any]) -> int:
    return (
        len(fragment.get("viewports") or [])
        + len(fragment.get("dimensions") or [])
        + len(fragment.get("indexes") or [])
        + len(fragment.get("materials") or [])
        + len(fragment.get("title_blocks") or [])
        + len(fragment.get("detail_titles") or [])
    )


def _fragment_text_count(fragment: Dict[str, Any]) -> int:
    try:
        return int(fragment.get("text_count") or 0)
    except (TypeError, ValueError):
        return 0


def _sheet_prefix(sheet_no: str) -> str:
    text = str(sheet_no or "").strip().upper()
    match = re.match(r"([A-Z]{2,})[\-._]?\d", text)
    if match:
        return match.group(1)
    return ""


def _build_fragment_payload(layout_payload: Dict[str, Any], fragment: Dict[str, Any]) -> Dict[str, Any]:
    fragment_payload = deepcopy(layout_payload)
    frame_id = str(fragment.get("frame_id") or "")
    frame = None
    for item in layout_payload.get("layout_frames") or []:
        if str(item.get("frame_id") or "") == frame_id:
            frame = deepcopy(item)
            break

    fragment_payload["sheet_no"] = str(fragment.get("sheet_no") or "").strip()
    fragment_payload["sheet_name"] = str(fragment.get("sheet_name") or "").strip()
    fragment_payload["scale"] = str(fragment.get("scale") or layout_payload.get("scale") or "").strip()
    fragment_payload["layout_frames"] = [frame] if frame else []
    fragment_payload["layout_fragments"] = [deepcopy(fragment)]
    fragment_payload["is_multi_sheet_layout"] = bool(layout_payload.get("is_multi_sheet_layout"))
    fragment_payload["title_blocks"] = deepcopy(fragment.get("title_blocks") or [])
    fragment_payload["detail_titles"] = deepcopy(fragment.get("detail_titles") or [])
    fragment_payload["indexes"] = deepcopy(fragment.get("indexes") or [])
    fragment_payload["dimensions"] = deepcopy(fragment.get("dimensions") or [])
    fragment_payload["materials"] = deepcopy(fragment.get("materials") or [])
    fragment_payload["pseudo_texts"] = deepcopy(fragment.get("pseudo_texts") or [])
    fragment_payload["viewports"] = deepcopy(fragment.get("viewports") or [])
    fragment_payload["material_table"] = []
    fragment_payload["fragment_id"] = str(fragment.get("fragment_id") or "")
    fragment_payload["fragment_bbox"] = deepcopy(fragment.get("fragment_bbox") or {})
    return fragment_payload


def expand_layout_json_units(json_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    layout_name = str(json_info.get("layout_name", "")).strip()
    layout_payload = deepcopy(json_info.get("data") or {})
    if not layout_payload:
        return [deepcopy(json_info)]

    fragments = layout_payload.get("layout_fragments") or []
    if len(fragments) <= 1:
        return [deepcopy(json_info)]

    identified_fragments = [fragment for fragment in fragments if _fragment_has_identity(fragment)]
    if not identified_fragments:
        return [deepcopy(json_info)]

    contentful_fragments = [fragment for fragment in identified_fragments if _fragment_content_score(fragment) > 0]

    text_only_fragments = [
        fragment
        for fragment in identified_fragments
        if _fragment_content_score(fragment) <= 0 and _fragment_text_count(fragment) >= 20
    ]

    text_prefix_counts: Dict[str, int] = {}
    for fragment in text_only_fragments:
        prefix = _sheet_prefix(str(fragment.get("sheet_no") or ""))
        if prefix:
            text_prefix_counts[prefix] = text_prefix_counts.get(prefix, 0) + 1

    clustered_text_only_fragments = [
        fragment
        for fragment in text_only_fragments
        if text_prefix_counts.get(_sheet_prefix(str(fragment.get("sheet_no") or "")), 0) >= 2
    ]

    contentful_fragments.extend(clustered_text_only_fragments)
    if not contentful_fragments:
        return [deepcopy(json_info)]

    layout_has_identity = bool(
        str(layout_payload.get("sheet_no") or "").strip() or str(layout_payload.get("sheet_name") or "").strip()
    )
    if len(identified_fragments) == 1 and layout_has_identity:
        return [deepcopy(json_info)]

    prefix_counts: Dict[str, int] = {}
    for fragment in identified_fragments:
        prefix = _sheet_prefix(str(fragment.get("sheet_no") or ""))
        if prefix:
            prefix_counts[prefix] = prefix_counts.get(prefix, 0) + 1

    dominant_prefix = ""
    dominant_count = 0
    if prefix_counts:
        dominant_prefix, dominant_count = max(prefix_counts.items(), key=lambda item: item[1])

    selected_fragments = list(contentful_fragments)
    if dominant_prefix and dominant_count >= max(3, math.ceil(len(identified_fragments) * 0.5)):
        for fragment in identified_fragments:
            if _sheet_prefix(str(fragment.get("sheet_no") or "")) == dominant_prefix:
                selected_fragments.append(fragment)

    deduped_fragments: List[Dict[str, Any]] = []
    seen_fragment_ids = set()
    for fragment in selected_fragments:
        fragment_id = str(fragment.get("fragment_id") or "")
        if fragment_id and fragment_id in seen_fragment_ids:
            continue
        if fragment_id:
            seen_fragment_ids.add(fragment_id)
        deduped_fragments.append(fragment)

    if not deduped_fragments:
        return [deepcopy(json_info)]

    expanded: List[Dict[str, Any]] = []
    for index, fragment in enumerate(deduped_fragments, start=1):
        payload = _build_fragment_payload(layout_payload, fragment)
        expanded.append(
            {
                **deepcopy(json_info),
                "layout_name": layout_name,
                "sheet_no": payload.get("sheet_no") or "",
                "sheet_name": payload.get("sheet_name") or "",
                "json_path": "",
                "viewports": payload.get("viewports") or [],
                "dimensions": payload.get("dimensions") or [],
                "pseudo_texts": payload.get("pseudo_texts") or [],
                "indexes": payload.get("indexes") or [],
                "title_blocks": payload.get("title_blocks") or [],
                "materials": payload.get("materials") or [],
                "material_table": payload.get("material_table") or [],
                "layers": payload.get("layers") or [],
                "data": payload,
                "is_fragment_unit": True,
                "fragment_id": str(fragment.get("fragment_id") or f"fragment-{index}"),
            }
        )

    return expanded or [deepcopy(json_info)]
