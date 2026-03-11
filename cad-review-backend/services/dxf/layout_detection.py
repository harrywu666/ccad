"""布局帧检测 + 分片构建。"""

from __future__ import annotations

from typing import Any, Dict, List, Sequence, Set, Tuple

from domain.text_cleaning import strip_mtext_formatting
from services.dxf.geo_utils import (
    _bbox_almost_equal,
    _bbox_area,
    _bbox_contains_point,
    _bbox_range,
    _bbox_size,
    _distance,
    _expand_bbox,
    _is_axis_aligned_rect,
    _point_in_range,
    _point_xy,
    _safe_float,
)
from services.dxf.text_utils import (
    _extract_sheet_no_from_text,
    _infer_paper_size_hint,
    _is_generic_layout_name,
    _is_numeric_like_text,
    _is_standalone_sheet_no_text,
)


def _collect_layout_frame_candidates(layout) -> List[Dict[str, Any]]:  # noqa: ANN001
    candidates: List[Dict[str, Any]] = []
    for entity in layout:
        entity_type = entity.dxftype()
        points: List[List[float]] = []

        try:
            if entity_type == "LWPOLYLINE":
                if not bool(entity.closed):
                    continue
                points = [[float(p[0]), float(p[1])] for p in entity.get_points("xy")]
            elif entity_type == "POLYLINE":
                if not bool(entity.is_closed):
                    continue
                points = [[float(vertex.dxf.location.x), float(vertex.dxf.location.y)] for vertex in entity.vertices]
            else:
                continue
        except Exception:  # noqa: BLE001
            continue

        bbox = _bbox_range(points)
        if bbox is None or not _is_axis_aligned_rect(points):
            continue

        width, height = _bbox_size(bbox)
        if width < 120.0 or height < 120.0:
            continue

        candidates.append(
            {
                "id": str(getattr(entity.dxf, "handle", "") or ""),
                "frame_bbox": bbox,
                "width": round(width, 3),
                "height": round(height, 3),
                "area": round(width * height, 3),
            }
        )

    candidates.sort(key=lambda item: item["area"], reverse=True)
    return candidates


def _object_position(item: Dict[str, Any]) -> List[float]:
    for key in ("position", "text_position", "center"):
        point = item.get(key)
        if isinstance(point, list) and len(point) >= 2:
            return [round(_safe_float(point[0]), 3), round(_safe_float(point[1]), 3)]
    return [0.0, 0.0]


def _infer_fragment_identity_from_texts(
    bbox: Dict[str, List[float]],
    text_entities: Sequence[Dict[str, Any]],
) -> Tuple[str, str]:
    width, height = _bbox_size(bbox)
    if width <= 0 or height <= 0:
        return "", ""

    candidate_bbox = _expand_bbox(bbox, x_padding=max(width * 0.08, 18.0), y_padding=max(height * 0.18, 24.0))
    lower_band_height = max(height * 0.28, 48.0)
    lower_band_downward_padding = max(height * 0.18, 24.0)
    lower_band = {
        "min": [bbox["min"][0], bbox["min"][1] - lower_band_downward_padding],
        "max": [bbox["max"][0], bbox["min"][1] + lower_band_height],
    }
    lower_band = _expand_bbox(lower_band, x_padding=max(width * 0.08, 18.0), y_padding=0.0)
    bottom_left_zone = {
        "min": [bbox["min"][0], lower_band["min"][1]],
        "max": [bbox["min"][0] + max(width * 0.42, 120.0), lower_band["max"][1]],
    }
    bottom_right_zone = {
        "min": [bbox["max"][0] - max(width * 0.42, 120.0), lower_band["min"][1]],
        "max": [bbox["max"][0], lower_band["max"][1]],
    }
    bottom_center_zone = {
        "min": [bbox["min"][0] + max(width * 0.24, 80.0), lower_band["min"][1]],
        "max": [bbox["max"][0] - max(width * 0.24, 80.0), lower_band["max"][1]],
    }

    metadata_keywords = (
        "图号", "图名", "图纸编号", "SHEET NO", "图纸标题", "DESCRIPTION",
        "比例", "SCALE", "修正", "REVISION", "图幅", "备注",
        "DRAWING CONTENTS", "图纸目录",
    )
    ignored_name_exact = {
        "图例", "说明", "N/A", "NO.", "SHEET NO.", "DESCRIPTION",
        "SCALE", "REVISION", "REMARK", "SHEET", "DRAWING CONTENTS",
        "CONSTRUCTION DRAWINGS",
    }

    best_sheet_no = ""
    best_sheet_no_score = -1.0
    best_sheet_name = ""
    best_sheet_name_score = -1.0
    zone_map = {
        "left": bottom_left_zone,
        "center": bottom_center_zone,
        "right": bottom_right_zone,
    }
    selected_zone_name = "right"
    selected_zone = bottom_right_zone
    zone_candidates = []
    for zone_name, zone_bbox in (
        ("left", bottom_left_zone),
        ("center", bottom_center_zone),
        ("right", bottom_right_zone),
    ):
        zone_score = 0.0
        zone_text_count = 0
        for item in text_entities:
            text = strip_mtext_formatting(str(item.get("text") or "")).strip()
            position = _point_xy(item.get("position"))
            if not text or not _bbox_contains_point(zone_bbox, position):
                continue
            zone_text_count += 1
            upper_text = text.upper()
            if any(keyword in text for keyword in metadata_keywords) or any(keyword in upper_text for keyword in metadata_keywords):
                zone_score += 4.0
            if _extract_sheet_no_from_text(text):
                zone_score += 1.5
            if zone_name == "center" and ("图名" in text or "图号" in text or "DRAWING" in upper_text):
                zone_score += 0.8
        zone_score += min(zone_text_count, 12) * 0.1
        zone_candidates.append((zone_score, zone_name, zone_bbox))
    zone_candidates.sort(key=lambda item: item[0], reverse=True)
    if zone_candidates and zone_candidates[0][0] > 0:
        selected_zone_name = zone_candidates[0][1]
        selected_zone = zone_candidates[0][2]

    zone_texts = []

    for item in text_entities:
        text = strip_mtext_formatting(str(item.get("text") or "")).strip()
        position = _point_xy(item.get("position"))
        if not text or not _bbox_contains_point(candidate_bbox, position):
            continue
        zone_texts.append({"text": text, "position": position})

        upper_text = text.upper()
        if any(keyword in text for keyword in ("版本", "日期")) or any(keyword in upper_text for keyword in ("VERSION", "DATE")):
            continue

        y_bonus = max(0.0, 1.0 - abs(position[1] - bbox["min"][1]) / max(height, 1.0))

        no_candidate = _extract_sheet_no_from_text(text)
        if no_candidate:
            normalized_candidate = no_candidate.upper()
            if normalized_candidate in {"A0", "A1", "A2", "A3", "A4"}:
                continue
            if not _is_standalone_sheet_no_text(text, no_candidate):
                continue
            containing_zone_name = ""
            for zn, zb in zone_map.items():
                if _bbox_contains_point(zb, position):
                    containing_zone_name = zn
                    break
            if not containing_zone_name:
                continue
            score = y_bonus + 2.5
            if containing_zone_name == selected_zone_name:
                score += 0.5
            if score > best_sheet_no_score:
                best_sheet_no = no_candidate
                best_sheet_no_score = score
                selected_zone_name = containing_zone_name
                selected_zone = zone_map[containing_zone_name]
    if best_sheet_no:
        no_positions = [item["position"] for item in zone_texts if _extract_sheet_no_from_text(item["text"]) == best_sheet_no]
    else:
        no_positions = []

    for item in zone_texts:
        text = item["text"]
        position = item["position"]
        upper_text = text.upper()
        if not _bbox_contains_point(selected_zone, position):
            continue
        if _is_numeric_like_text(text) or len(text) > 36:
            continue
        if text in ignored_name_exact:
            continue
        if any(keyword in text for keyword in ("版本", "日期", "注：", "注:", "原土建", "改动", "取消")):
            continue
        if any(keyword in upper_text for keyword in ("VERSION", "DATE")):
            continue
        if any(symbol in text for symbol in ("：", ":", "，", ",", "。", "；", ";")):
            continue
        if any(keyword in text for keyword in metadata_keywords) or any(keyword in upper_text for keyword in metadata_keywords):
            continue
        if _extract_sheet_no_from_text(text):
            continue

        has_chinese = any("\u4e00" <= ch <= "\u9fff" for ch in text)
        has_alpha = any(ch.isalpha() for ch in text)
        if not has_chinese and not has_alpha:
            continue

        score = min(len(text), 24) / 24.0
        if has_chinese:
            score += 0.8
        if "图" in text or "说明" in text or "布置" in text or "DETAIL" in upper_text:
            score += 0.6
        if no_positions:
            distance = min(_distance(position, no_pos) for no_pos in no_positions)
            min_y_delta = min(abs(position[1] - no_pos[1]) for no_pos in no_positions)
            if distance > max(width * 0.35, 120.0):
                continue
            if min_y_delta > max(height * 0.12, 28.0):
                continue
            score += max(0.0, 2.0 - (distance / max(width * 0.45, 120.0)) * 2.0)
        else:
            score += max(0.0, 1.0 - abs(position[1] - bbox["min"][1]) / max(height, 1.0))
        if score > best_sheet_name_score:
            best_sheet_name = text
            best_sheet_name_score = score

    return best_sheet_no, best_sheet_name


def _detect_layout_frames(
    layout,
    *,
    layout_page_range: Dict[str, List[float]],
    title_blocks: List[Dict[str, Any]],
    detail_titles: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:  # noqa: ANN001
    candidates = _collect_layout_frame_candidates(layout)
    anchors = title_blocks + detail_titles
    frames: List[Dict[str, Any]] = []
    used_ids: Set[str] = set()
    page_area = _bbox_area(layout_page_range)

    for candidate in candidates:
        bbox = candidate["frame_bbox"]
        candidate_area = _bbox_area(bbox)
        if page_area > 0 and (candidate_area / page_area) < 0.12:
            continue
        contained_anchor_count = 0
        for item in anchors:
            point = _object_position(item)
            if _bbox_contains_point(bbox, point, padding=12.0):
                contained_anchor_count += 1

        if anchors and contained_anchor_count == 0:
            continue

        duplicate = False
        for existing in frames:
            existing_bbox = existing["frame_bbox"]
            if _bbox_almost_equal(existing_bbox, bbox, tolerance=2.0):
                duplicate = True
                break
        if duplicate:
            continue

        width = candidate["width"]
        height = candidate["height"]
        frames.append(
            {
                "frame_id": candidate["id"] or f"frame-{len(frames) + 1}",
                "frame_bbox": bbox,
                "paper_size_hint": _infer_paper_size_hint(width, height),
                "orientation": "landscape" if width >= height else "portrait",
                "confidence": 1.0 if contained_anchor_count > 0 else 0.75,
            }
        )
        used_ids.add(candidate["id"])

    if frames:
        return frames

    page_width, page_height = _bbox_size(layout_page_range)
    if page_width <= 0 or page_height <= 0:
        return []

    return [
        {
            "frame_id": "frame-1",
            "frame_bbox": layout_page_range,
            "paper_size_hint": _infer_paper_size_hint(page_width, page_height),
            "orientation": "landscape" if page_width >= page_height else "portrait",
            "confidence": 0.5,
        }
    ]


def _build_layout_fragments(
    frames: List[Dict[str, Any]],
    *,
    title_blocks: List[Dict[str, Any]],
    detail_titles: List[Dict[str, Any]],
    indexes: List[Dict[str, Any]],
    dimensions: List[Dict[str, Any]],
    materials: List[Dict[str, Any]],
    pseudo_texts: List[Dict[str, Any]],
    viewports: List[Dict[str, Any]],
    text_entities: List[Dict[str, Any]],
    fallback_sheet_no: str,
    fallback_sheet_name: str,
    layout_name: str,
) -> List[Dict[str, Any]]:
    if not frames:
        return []

    fragments: List[Dict[str, Any]] = []
    for idx, frame in enumerate(frames, start=1):
        bbox = frame["frame_bbox"]
        width, height = _bbox_size(bbox)
        frame_viewports = [item for item in viewports if _bbox_contains_point(bbox, _object_position(item), padding=12.0)]

        def in_fragment_model_ranges(point: Sequence[float]) -> bool:
            for viewport in frame_viewports:
                model_range = viewport.get("model_range") or {}
                if _point_in_range(point, model_range, padding=200.0):
                    return True
            return False

        def _fragment_contains_item(
            item: Dict[str, Any],
            *,
            position_getter,
            layout_padding: float = 12.0,
        ) -> bool:
            point = position_getter(item)
            if item.get("source") == "model_space":
                return bool(frame_viewports) and in_fragment_model_ranges(point)
            return _bbox_contains_point(bbox, point, padding=layout_padding)

        fragment_title_blocks = [item for item in title_blocks if _bbox_contains_point(bbox, _object_position(item), padding=12.0)]
        fragment_detail_titles = [item for item in detail_titles if _bbox_contains_point(bbox, _object_position(item), padding=12.0)]
        fragment_indexes = [
            item
            for item in indexes
            if _fragment_contains_item(item, position_getter=_object_position, layout_padding=12.0)
        ]
        fragment_dimensions = [
            item
            for item in dimensions
            if _fragment_contains_item(item, position_getter=_object_position, layout_padding=12.0)
        ]
        fragment_materials = [
            item
            for item in materials
            if _fragment_contains_item(item, position_getter=_object_position, layout_padding=12.0)
        ]
        fragment_pseudo_texts = [
            item
            for item in pseudo_texts
            if _fragment_contains_item(item, position_getter=lambda candidate: _point_xy(candidate.get("position")), layout_padding=8.0)
        ]
        fragment_text_entities = [
            item
            for item in text_entities
            if _bbox_contains_point(bbox, _point_xy(item.get("position")), padding=8.0)
        ]
        identity_text_bbox = _expand_bbox(
            {
                "min": [bbox["min"][0], bbox["min"][1] - max(height * 0.18, 24.0)],
                "max": [bbox["max"][0], bbox["max"][1]],
            },
            x_padding=max(width * 0.08, 18.0),
            y_padding=0.0,
        )
        identity_text_entities = [
            item
            for item in text_entities
            if _bbox_contains_point(identity_text_bbox, _point_xy(item.get("position")))
        ]

        title_sheet_no = ""
        title_sheet_name = ""
        for item in fragment_title_blocks:
            candidate_sheet_no = str(item.get("sheet_no") or "").strip()
            candidate_sheet_name = str(item.get("sheet_name") or "").strip()
            if candidate_sheet_no and not title_sheet_no:
                title_sheet_no = candidate_sheet_no
            if candidate_sheet_name and not title_sheet_name:
                title_sheet_name = candidate_sheet_name

        for item in fragment_detail_titles:
            candidate_sheet_no = str(item.get("sheet_no") or "").strip()
            if candidate_sheet_no and not title_sheet_no:
                title_sheet_no = candidate_sheet_no

        fallback_single_sheet_no = fallback_sheet_no if len(frames) == 1 else ""
        fallback_single_sheet_name = fallback_sheet_name if len(frames) == 1 else ""

        sheet_no = title_sheet_no or fallback_single_sheet_no
        sheet_name = title_sheet_name or ("" if _is_generic_layout_name(fallback_single_sheet_name) else fallback_single_sheet_name)
        if not sheet_no or not sheet_name:
            inferred_sheet_no, inferred_sheet_name = _infer_fragment_identity_from_texts(bbox, identity_text_entities)
            if not sheet_no and inferred_sheet_no:
                sheet_no = inferred_sheet_no
            if not sheet_name and inferred_sheet_name:
                sheet_name = inferred_sheet_name

        fragments.append(
            {
                "fragment_id": f"{frame['frame_id']}-fragment-{idx}",
                "frame_id": frame["frame_id"],
                "layout_name": layout_name,
                "fragment_bbox": bbox,
                "sheet_no": sheet_no,
                "sheet_name": sheet_name,
                "scale": "",
                "title_blocks": fragment_title_blocks,
                "detail_titles": fragment_detail_titles,
                "indexes": fragment_indexes,
                "dimensions": fragment_dimensions,
                "materials": fragment_materials,
                "pseudo_texts": fragment_pseudo_texts,
                "viewports": frame_viewports,
                "text_count": len(fragment_text_entities),
                "fragment_confidence": frame.get("confidence", 0.5),
            }
        )

    return fragments
