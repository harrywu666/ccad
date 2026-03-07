"""
DXF 数据提取服务
技术路线：ODA File Converter（DWG -> DXF） + ezdxf（按Layout提取JSON）
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from domain.text_cleaning import strip_mtext_formatting
from services.coordinate_service import enrich_json_with_coordinates

logger = logging.getLogger(__name__)


MODEL_LAYOUT_NAMES = {
    "model",
    "modelspace",
    "model_space",
    "模型",
    "模型空间",
}

INDEX_KEYWORDS = ("索引", "INDEX", "SYMB", "SYM")
TITLE_KEYWORDS = ("图签", "TB", "TITLE", "标题")
MATERIAL_LAYER_KEYWORDS = ("MAT", "MATERIAL", "材料")


def _normalize_name(name: str) -> str:
    return re.sub(r"[\s\-_./\\()（）【】\[\]{}:：|]+", "", (name or "").strip().lower())


def _is_model_layout(name: str) -> bool:
    return _normalize_name(name) in MODEL_LAYOUT_NAMES


def _sanitize_filename(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", value).strip("_") or "layout"


def _extract_sheet_no_from_text(text: str) -> str:
    if not text:
        return ""

    patterns = [
        r"[A-Za-z]{1,3}\d{0,3}[.\-_]\d{1,3}[a-zA-Z]?",
        r"[A-Za-z]\d{1,4}[a-zA-Z]?",
        r"\d{2}[.\-_]\d{2}[a-zA-Z]?",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(0)
    upper = (text or "").upper()
    if "COVER" in upper:
        return "COVER"
    return ""


def _is_sheet_no_like(text: str) -> bool:
    if not text:
        return False
    return _extract_sheet_no_from_text(text) != ""


def _extract_sheet_name_from_layout(layout_name: str, sheet_no: str) -> str:
    if not layout_name:
        return ""
    if not sheet_no:
        return layout_name.strip()
    return layout_name.replace(sheet_no, "", 1).strip(" -_:.|")


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _point_xy(point: Any) -> List[float]:
    if point is None:
        return [0.0, 0.0]

    if hasattr(point, "x") and hasattr(point, "y"):
        return [round(_safe_float(point.x), 3), round(_safe_float(point.y), 3)]

    if isinstance(point, Sequence) and len(point) >= 2:
        return [round(_safe_float(point[0]), 3), round(_safe_float(point[1]), 3)]

    return [0.0, 0.0]


def _point_in_range(point: Sequence[float], model_range: Dict[str, List[float]], padding: float = 0.0) -> bool:
    if len(point) < 2:
        return False
    min_x, min_y = model_range.get("min", [0.0, 0.0])
    max_x, max_y = model_range.get("max", [0.0, 0.0])
    x, y = _safe_float(point[0]), _safe_float(point[1])
    return (min_x - padding) <= x <= (max_x + padding) and (min_y - padding) <= y <= (max_y + padding)


def _distance(p1: Sequence[float], p2: Sequence[float]) -> float:
    if len(p1) < 2 or len(p2) < 2:
        return 1e9
    dx = _safe_float(p1[0]) - _safe_float(p2[0])
    dy = _safe_float(p1[1]) - _safe_float(p2[1])
    return (dx * dx + dy * dy) ** 0.5


def _display_scale(scale: float) -> str:
    if scale <= 0:
        return ""
    ratio = round(1.0 / scale)
    if ratio <= 0:
        return ""
    return f"1:{ratio}"


def _normalize_plain_text(text: str) -> str:
    return strip_mtext_formatting(text)


def _is_numeric_like_text(text: str) -> bool:
    s = _normalize_plain_text(text).upper()
    if not s:
        return False
    s = s.replace("MM", "").replace(",", "").replace(" ", "")
    return bool(re.fullmatch(r"[+-]?\d+(\.\d+)?", s))


def _parse_numeric_text(text: str) -> Optional[float]:
    s = _normalize_plain_text(text).upper()
    s = s.replace("MM", "").replace(",", "").replace(" ", "")
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def _collect_text_entities(layout) -> List[Dict[str, Any]]:  # noqa: ANN001
    texts: List[Dict[str, Any]] = []

    for entity in layout.query("TEXT"):
        text = str(getattr(entity.dxf, "text", "") or "").strip()
        if text:
            texts.append({"text": text, "position": _point_xy(getattr(entity.dxf, "insert", None))})

    for entity in layout.query("MTEXT"):
        text = strip_mtext_formatting(str(getattr(entity, "text", "") or ""))
        if text:
            texts.append({"text": text, "position": _point_xy(getattr(entity.dxf, "insert", None))})

    return texts


def _collect_layer_states(doc) -> List[Dict[str, Any]]:  # noqa: ANN001
    items: List[Dict[str, Any]] = []
    for layer in doc.layers:
        name = str(getattr(layer.dxf, "name", "") or "")
        is_on = not bool(layer.is_off())
        is_frozen = bool(layer.is_frozen())
        is_locked = bool(layer.is_locked())
        items.append(
            {
                "name": name,
                "visible": bool(is_on and not is_frozen),
                "on": bool(is_on),
                "frozen": bool(is_frozen),
                "locked": bool(is_locked),
            }
        )
    return items


def get_oda_path() -> str:
    """
    获取 ODA File Converter 可执行路径。
    支持环境变量 ODA_FILE_CONVERTER_PATH 覆盖。
    """
    env_path = os.getenv("ODA_FILE_CONVERTER_PATH", "").strip()
    if env_path:
        candidate = Path(env_path).expanduser()
        if candidate.exists():
            return str(candidate)

    if platform.system() == "Darwin":
        default = Path("/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter")
    elif platform.system() == "Windows":
        default = Path(r"C:\Program Files\ODA\ODAFileConverter\ODAFileConverter.exe")
    else:
        default = Path("/usr/bin/ODAFileConverter")

    if default.exists():
        return str(default)

    raise RuntimeError("请先安装ODA File Converter")


def dwg_batch_to_dxf(input_dir: str, output_dir: str) -> List[str]:
    """
    批量将 input_dir 中 DWG 转为 DXF，返回 DXF 路径列表。
    """
    in_dir = Path(input_dir).expanduser().resolve()
    out_dir = Path(output_dir).expanduser().resolve()
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    oda = get_oda_path()
    cmd = [oda, str(in_dir), str(out_dir), "ACAD2018", "DXF", "0", "1"]
    logger.info("执行ODA转换: %s", " ".join(cmd))

    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()
        stdout = (proc.stdout or "").strip()
        raise RuntimeError(f"ODA转换失败: rc={proc.returncode}, stderr={stderr[:500]}, stdout={stdout[:500]}")

    dxf_files = sorted(
        [
            str(path.resolve())
            for path in out_dir.iterdir()
            if path.is_file() and path.suffix.lower() == ".dxf"
        ]
    )
    return dxf_files


def dwg_to_dxf(dwg_path: str, output_dir: str) -> str:
    """
    单文件DWG转DXF。
    """
    src = Path(dwg_path).expanduser().resolve()
    if not src.exists():
        raise FileNotFoundError(f"DWG文件不存在: {src}")

    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="dwg_one_in_") as in_dir:
        copied = Path(in_dir) / src.name
        shutil.copy2(src, copied)
        dxfs = dwg_batch_to_dxf(in_dir, str(out_dir))

    stem = src.stem.lower()
    for dxf in dxfs:
        if Path(dxf).stem.lower() == stem:
            return dxf

    if not dxfs:
        raise RuntimeError("ODA转换完成但未找到DXF输出")

    return dxfs[0]


def calc_model_range(viewport) -> Dict[str, List[float]]:  # noqa: ANN001
    """
    从 VIEWPORT 计算对应模型空间范围。
    """
    if hasattr(viewport, "get_modelspace_limits"):
        try:
            x0, y0, x1, y1 = viewport.get_modelspace_limits()
            if x1 > x0 and y1 > y0:
                return {
                    "min": [round(_safe_float(x0), 3), round(_safe_float(y0), 3)],
                    "max": [round(_safe_float(x1), 3), round(_safe_float(y1), 3)],
                }
        except Exception:  # noqa: BLE001
            pass

    center = getattr(viewport.dxf, "view_center_point", None)
    cx, cy = _point_xy(center)

    model_height = _safe_float(getattr(viewport.dxf, "view_height", 0.0))
    vp_width = _safe_float(getattr(viewport.dxf, "width", 0.0))
    vp_height = _safe_float(getattr(viewport.dxf, "height", 0.0))

    if model_height <= 0.0:
        model_height = _safe_float(vp_height, 0.0)
    if vp_height <= 0.0:
        vp_height = 1.0

    model_width = model_height * (vp_width / vp_height)

    return {
        "min": [round(cx - model_width / 2.0, 3), round(cy - model_height / 2.0, 3)],
        "max": [round(cx + model_width / 2.0, 3), round(cy + model_height / 2.0, 3)],
    }


def get_visible_layers(doc, viewport) -> Set[str]:  # noqa: ANN001
    """
    获取给定视口下可见图层集合。
    """
    layer_names = set()
    for layer in doc.layers:
        name = str(getattr(layer.dxf, "name", "") or "")
        if not name:
            continue
        if layer.is_off() or layer.is_frozen():
            continue
        layer_names.add(name)

    frozen = set()
    if hasattr(viewport, "frozen_layers"):
        try:
            frozen = {str(name) for name in viewport.frozen_layers}
        except Exception:  # noqa: BLE001
            frozen = set()

    if hasattr(viewport, "get_frozen_layer_names"):
        try:
            frozen = frozen.union({str(name) for name in viewport.get_frozen_layer_names()})
        except Exception:  # noqa: BLE001
            pass

    return {name for name in layer_names if name not in frozen}


def _pick_main_viewport(layout) -> Optional[Any]:  # noqa: ANN001
    best_vp = None
    best_area = -1.0

    for vp in layout.query("VIEWPORT"):
        vp_id = int(_safe_float(getattr(vp.dxf, "id", 0), 0.0))
        if vp_id == 1:
            continue

        width = _safe_float(getattr(vp.dxf, "width", 0.0))
        height = _safe_float(getattr(vp.dxf, "height", 0.0))
        area = width * height
        if area > best_area:
            best_area = area
            best_vp = vp

    return best_vp


def _extract_dimensions(doc, layout, model_range: Dict[str, List[float]], visible_layers: Set[str]) -> List[Dict[str, Any]]:  # noqa: ANN001
    items: List[Dict[str, Any]] = []

    def make_item(dim, source: str) -> Optional[Dict[str, Any]]:  # noqa: ANN001
        layer = str(getattr(dim.dxf, "layer", "") or "")
        if visible_layers and layer and layer not in visible_layers:
            return None

        defpoint = _point_xy(getattr(dim.dxf, "defpoint", None))
        defpoint2 = _point_xy(getattr(dim.dxf, "defpoint2", None))
        text_pos = _point_xy(
            getattr(dim.dxf, "text_midpoint", None) or getattr(dim.dxf, "defpoint", None)
        )

        if source == "model_space" and model_range and not _point_in_range(text_pos, model_range, padding=200.0):
            return None

        value = getattr(dim.dxf, "actual_measurement", None)
        if value is None:
            try:
                value = dim.get_measurement()
            except Exception:  # noqa: BLE001
                value = 0.0

        display_text = str(getattr(dim.dxf, "text", "") or "")
        if display_text in {"", "<>"}:
            display_text = str(round(_safe_float(value), 3)).rstrip("0").rstrip(".")

        return {
            "id": str(getattr(dim.dxf, "handle", "") or ""),
            "value": round(_safe_float(value), 6),
            "display_text": display_text,
            "layer": layer,
            "source": source,
            "defpoint": defpoint,
            "defpoint2": defpoint2,
            "text_position": text_pos,
        }

    for dim in doc.modelspace().query("DIMENSION"):
        item = make_item(dim, "model_space")
        if item:
            items.append(item)

    for dim in layout.query("DIMENSION"):
        item = make_item(dim, "layout_space")
        if item:
            items.append(item)

    return items


def _extract_pseudo_texts(doc, layout, model_range: Dict[str, List[float]], visible_layers: Set[str]) -> List[Dict[str, Any]]:  # noqa: ANN001
    items: List[Dict[str, Any]] = []

    def collect(space, source: str) -> None:  # noqa: ANN001
        for entity in space.query("TEXT MTEXT"):
            etype = entity.dxftype()
            layer = str(getattr(entity.dxf, "layer", "") or "")
            if visible_layers and layer and layer not in visible_layers:
                continue

            if etype == "TEXT":
                raw_text = str(getattr(entity.dxf, "text", "") or "")
                pos = _point_xy(getattr(entity.dxf, "insert", None))
            else:
                raw_text = str(getattr(entity, "text", "") or "")
                pos = _point_xy(getattr(entity.dxf, "insert", None))

            text = _normalize_plain_text(raw_text)
            if not _is_numeric_like_text(text):
                continue

            if source == "model_space" and model_range and not _point_in_range(pos, model_range, padding=200.0):
                continue

            numeric_value = _parse_numeric_text(text)
            items.append(
                {
                    "id": str(getattr(entity.dxf, "handle", "") or ""),
                    "entity_type": etype,
                    "content": text,
                    "numeric_value": numeric_value if numeric_value is not None else 0.0,
                    "position": pos,
                    "layer": layer,
                    "source": source,
                }
            )

    collect(doc.modelspace(), "model_space")
    collect(layout, "layout_space")
    return items


def _extract_insert_info(layout) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], str, str]:  # noqa: ANN001
    indexes: List[Dict[str, Any]] = []
    title_blocks: List[Dict[str, Any]] = []
    first_sheet_no = ""
    first_sheet_name = ""

    for insert in layout.query("INSERT"):
        block_name = str(getattr(insert.dxf, "name", "") or "")
        upper_name = block_name.upper()
        layer = str(getattr(insert.dxf, "layer", "") or "")
        position = _point_xy(getattr(insert.dxf, "insert", None))

        attrs: Dict[str, str] = {}
        for attrib in getattr(insert, "attribs", []):
            tag = str(getattr(attrib.dxf, "tag", "") or "").upper().strip()
            text = str(getattr(attrib.dxf, "text", "") or "").strip()
            if tag:
                attrs[tag] = text

        index_no_keys = (
            "_ACM-CALLOUTNUMBER",
            "_ACM-SECTIONLABEL",
            "REF#",
            "INDEX_NO",
            "INDEX",
            "NO",
            "NUM",
            "编号",
            "序号",
            "SN",
            "DN",
        )
        target_sheet_keys = (
            "_ACM-SHEETNUMBER",
            "SHT",
            "SHEET",
            "TARGET",
            "图号",
            "DRAWINGNO",
            "DRAWNO",
            "SHEETNO",
        )
        title_no_keys = ("图号", "DRAWNO", "DRAWINGNO", "SHEETNO")
        title_name_keys = ("图名", "DRAWNAME", "SHEETNAME", "_ACM-TITLEMARK")

        def pick_attr(keys) -> str:  # noqa: ANN001
            for key in keys:
                if attrs.get(key):
                    return attrs[key]
            return ""

        idx_no_candidate = pick_attr(index_no_keys)
        target_candidate = pick_attr(target_sheet_keys)

        # 常见索引写法：REF# + SHT / _ACM-CALLOUTNUMBER + _ACM-SHEETNUMBER
        has_index_pair = bool(idx_no_candidate and target_candidate)
        has_index_tag = any(any(keyword in key for keyword in INDEX_KEYWORDS) for key in attrs)
        has_callout_tag = any(key in attrs for key in ("_ACM-CALLOUTNUMBER", "_ACM-SECTIONLABEL", "REF#"))
        has_sheet_ref_tag = any(key in attrs for key in ("_ACM-SHEETNUMBER", "SHT", "SHEET", "SHEETNO"))

        is_index = (
            any(keyword in upper_name for keyword in INDEX_KEYWORDS)
            or has_index_tag
            or has_index_pair
            or (has_callout_tag and has_sheet_ref_tag)
        )

        is_title = (
            any(keyword in upper_name for keyword in TITLE_KEYWORDS)
            or any(key in attrs for key in ("_ACM-TITLELABEL", "_ACM-TITLEMARK", "_ACM-VPSCALE"))
            or any(key in attrs for key in title_no_keys + title_name_keys)
        )

        if is_index:
            index_no = idx_no_candidate
            target_sheet = target_candidate
            indexes.append(
                {
                    "id": str(getattr(insert.dxf, "handle", "") or ""),
                    "block_name": block_name,
                    "index_no": index_no,
                    "target_sheet": target_sheet,
                    "source": "layout_space",
                    "position": position,
                    "layer": layer,
                    "attrs": [{"tag": k, "value": v} for k, v in attrs.items()],
                }
            )

        if is_title:
            sheet_no = pick_attr(title_no_keys)
            sheet_name = pick_attr(title_name_keys)

            if not first_sheet_no and sheet_no:
                first_sheet_no = sheet_no
            if not first_sheet_name and sheet_name:
                first_sheet_name = sheet_name

            title_blocks.append(
                {
                    "id": str(getattr(insert.dxf, "handle", "") or ""),
                    "block_name": block_name,
                    "sheet_no": sheet_no,
                    "sheet_name": sheet_name,
                    "position": position,
                    "layer": layer,
                    "attrs": [{"tag": k, "value": v} for k, v in attrs.items()],
                }
            )

    return indexes, title_blocks, first_sheet_no, first_sheet_name


def _extract_materials(layout) -> List[Dict[str, Any]]:  # noqa: ANN001
    items: List[Dict[str, Any]] = []
    text_entities = _collect_text_entities(layout)

    try:
        ml_entities = list(layout.query("MLEADER"))
    except Exception:  # noqa: BLE001
        ml_entities = []

    try:
        ml_entities += list(layout.query("MULTILEADER"))
    except Exception:  # noqa: BLE001
        pass

    for ml in ml_entities:
        layer = str(getattr(ml.dxf, "layer", "") or "")
        content = ""
        if hasattr(ml, "get_mtext_content"):
            try:
                content = str(ml.get_mtext_content() or "")
            except Exception:  # noqa: BLE001
                content = ""
        if not content:
            content = str(getattr(ml.dxf, "text", "") or "")
        content = strip_mtext_formatting(content)

        arrow = _point_xy(
            getattr(ml.dxf, "insert", None)
            or getattr(ml.dxf, "base_point", None)
            or getattr(ml.dxf, "arrow_head", None)
        )

        token = content.split()[0] if content else ""
        code = token if token and re.search(r"\d", token) else ""

        if content or any(keyword in layer.upper() for keyword in MATERIAL_LAYER_KEYWORDS):
            items.append(
                {
                    "id": str(getattr(ml.dxf, "handle", "") or ""),
                    "entity_type": "MLEADER",
                    "content": content,
                    "code": code,
                    "position": arrow,
                    "arrow": arrow,
                    "layer": layer,
                }
            )

    for leader in layout.query("LEADER"):
        layer = str(getattr(leader.dxf, "layer", "") or "")
        vertices = []
        if hasattr(leader, "vertices"):
            try:
                vertices = [
                    _point_xy(point)
                    for point in leader.vertices()  # pyright: ignore[reportCallIssue]
                ]
            except Exception:  # noqa: BLE001
                vertices = []

        arrow = vertices[0] if vertices else _point_xy(getattr(leader.dxf, "insert", None))

        nearest_text = ""
        nearest_dist = 1e9
        for text_obj in text_entities:
            dist = _distance(arrow, text_obj["position"])
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_text = text_obj["text"]

        if nearest_dist > 50.0:
            nearest_text = ""

        token = nearest_text.strip().split()[0] if nearest_text.strip() else ""
        code = token if token and re.search(r"\d", token) else ""

        if nearest_text or any(keyword in layer.upper() for keyword in MATERIAL_LAYER_KEYWORDS):
            items.append(
                {
                    "id": str(getattr(leader.dxf, "handle", "") or ""),
                    "entity_type": "LEADER",
                    "content": nearest_text,
                    "code": code,
                    "position": arrow,
                    "arrow": arrow,
                    "layer": layer,
                }
            )

    return items


def _pair_material_rows_from_text(layout) -> List[Dict[str, str]]:  # noqa: ANN001
    texts = _collect_text_entities(layout)
    if not texts:
        return []

    # 先按Y聚类，再在行内按X排序，做 code+name 拼合
    texts_sorted = sorted(texts, key=lambda item: (-item["position"][1], item["position"][0]))

    rows: List[List[Dict[str, Any]]] = []
    row_tol = 30.0
    for item in texts_sorted:
        if not rows:
            rows.append([item])
            continue

        row_y = rows[-1][0]["position"][1]
        if abs(item["position"][1] - row_y) <= row_tol:
            rows[-1].append(item)
        else:
            rows.append([item])

    pairs: List[Dict[str, str]] = []
    seen = set()
    for row in rows:
        row_sorted = sorted(row, key=lambda item: item["position"][0])
        line = " ".join(item["text"] for item in row_sorted).strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue

        code = parts[0].strip()
        name = " ".join(parts[1:]).strip()
        if not re.search(r"\d", code) or not name:
            continue

        key = (code.upper(), name.upper())
        if key in seen:
            continue
        seen.add(key)
        pairs.append({"code": code, "name": name})

    return pairs


def _extract_material_table(layout) -> List[Dict[str, str]]:  # noqa: ANN001
    rows: List[Dict[str, str]] = []
    seen = set()

    for table in layout.query("TABLE"):
        n_rows = int(_safe_float(getattr(table, "n_rows", 0), 0.0))
        n_cols = int(_safe_float(getattr(table, "n_cols", 0), 0.0))

        if n_rows <= 0 or n_cols <= 0:
            # 兜底走文本拼合
            continue

        for ridx in range(n_rows):
            try:
                c0 = strip_mtext_formatting(str(table.get_cell_text(ridx, 0) or ""))
            except Exception:  # noqa: BLE001
                c0 = ""
            try:
                c1 = strip_mtext_formatting(str(table.get_cell_text(ridx, 1) or "")) if n_cols > 1 else ""
            except Exception:  # noqa: BLE001
                c1 = ""

            if not re.search(r"\d", c0) or not c1:
                continue

            key = (c0.upper(), c1.upper())
            if key in seen:
                continue
            seen.add(key)
            rows.append({"code": c0, "name": c1})

    if rows:
        return rows

    return _pair_material_rows_from_text(layout)


def _collect_viewports(layout, model_range: Dict[str, List[float]], active_layer: str) -> List[Dict[str, Any]]:  # noqa: ANN001
    items: List[Dict[str, Any]] = []
    for vp in layout.query("VIEWPORT"):
        vp_id = int(_safe_float(getattr(vp.dxf, "id", 0), 0.0))
        if vp_id == 1:
            continue

        center = _point_xy(getattr(vp.dxf, "center", None))
        scale = _safe_float(getattr(vp.dxf, "scale", 0.0), 0.0)
        vp_model_range = calc_model_range(vp)
        items.append(
            {
                "id": str(getattr(vp.dxf, "handle", "") or ""),
                "viewport_id": vp_id,
                "position": center,
                "width": _safe_float(getattr(vp.dxf, "width", 0.0), 0.0),
                "height": _safe_float(getattr(vp.dxf, "height", 0.0), 0.0),
                "scale": scale,
                "layer": str(getattr(vp.dxf, "layer", "") or ""),
                "active_layer": active_layer,
                "frozen_layers": [],
                "model_range": vp_model_range if vp_model_range.get("max") != vp_model_range.get("min") else model_range,
            }
        )
    return items


def extract_layout(doc, layout_name: str, dwg_filename: str) -> Optional[Dict[str, Any]]:  # noqa: ANN001
    """
    按单个 Layout 提取 JSON 数据。
    """
    if _is_model_layout(layout_name):
        return None

    try:
        layout = doc.layouts.get(layout_name)
    except Exception:  # noqa: BLE001
        return None

    if layout is None:
        return None

    main_vp = _pick_main_viewport(layout)

    if main_vp is not None:
        model_range = calc_model_range(main_vp)
        visible_layers = get_visible_layers(doc, main_vp)
        if hasattr(main_vp, "get_scale"):
            try:
                scale = _safe_float(main_vp.get_scale(), 0.0)
            except Exception:  # noqa: BLE001
                scale = _safe_float(getattr(main_vp.dxf, "scale", 0.0), 0.0)
        else:
            scale = _safe_float(getattr(main_vp.dxf, "scale", 0.0), 0.0)
    else:
        model_range = {"min": [0.0, 0.0], "max": [0.0, 0.0]}
        visible_layers = {str(getattr(layer.dxf, "name", "") or "") for layer in doc.layers if not layer.is_off()}
        scale = 0.0

    dimensions = _extract_dimensions(doc, layout, model_range, visible_layers)
    pseudo_texts = _extract_pseudo_texts(doc, layout, model_range, visible_layers)
    indexes, title_blocks, title_sheet_no, title_sheet_name = _extract_insert_info(layout)
    materials = _extract_materials(layout)
    material_table = _extract_material_table(layout)
    layers = _collect_layer_states(doc)

    title_no = (title_sheet_no or "").strip()
    layout_no = _extract_sheet_no_from_text(layout_name)
    dwg_no = _extract_sheet_no_from_text(dwg_filename)
    sheet_no = title_no if _is_sheet_no_like(title_no) else (layout_no or dwg_no)
    sheet_name = title_sheet_name or _extract_sheet_name_from_layout(layout_name, sheet_no)

    active_layer = str(getattr(doc.header, "$CLAYER", "") or "")
    viewports = _collect_viewports(layout, model_range, active_layer)

    payload: Dict[str, Any] = {
        "source_dwg": dwg_filename,
        "layout_name": layout_name,
        "sheet_no": sheet_no,
        "sheet_name": sheet_name,
        "extracted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_version": 1,
        "scale": _display_scale(scale),
        "model_range": model_range,
        "viewports": viewports,
        "dimensions": dimensions,
        "pseudo_texts": pseudo_texts,
        "indexes": indexes,
        "title_blocks": title_blocks,
        "materials": materials,
        "material_table": material_table,
        "layers": layers,
    }

    return enrich_json_with_coordinates(payload)


def _write_layout_json(output_dir: Path, dwg_stem: str, layout_payload: Dict[str, Any]) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{_sanitize_filename(dwg_stem)}_{_sanitize_filename(layout_payload.get('layout_name', 'layout'))}.json"
    path = output_dir / file_name
    path.write_text(json.dumps(layout_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return str(path)


def _list_dwg_paths(paths: Iterable[str]) -> List[Path]:
    out = []
    for item in paths:
        path = Path(str(item)).expanduser().resolve()
        if path.exists() and path.suffix.lower() == ".dwg":
            out.append(path)
    return out


def process_dwg_files(
    dwg_paths: Sequence[str],
    project_id: str,
    output_dir: str,
    progress_callback: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[Dict[str, Any]]:
    """
    批量处理DWG：ODA批量转DXF + ezdxf按布局提取JSON。

    返回：
    [
      {
        'dwg_path': '/abs/a.dwg',
        'dwg': 'a.dwg',
        'layout_name': '平面布置图',
        'sheet_no': 'A1-01',
        'sheet_name': '平面布置图',
        'json_path': '/abs/out/a_平面布置图.json',
        'data': {...}
      }
    ]
    """
    resolved_dwgs = _list_dwg_paths(dwg_paths)
    if not resolved_dwgs:
        return []

    try:
        import ezdxf  # noqa: WPS433
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"缺少ezdxf依赖，请安装后重试: {exc}") from exc

    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    results: List[Dict[str, Any]] = []

    with tempfile.TemporaryDirectory(prefix="ccad_dwg_in_") as tmp_in, tempfile.TemporaryDirectory(
        prefix="ccad_dxf_out_"
    ) as tmp_out:
        tmp_in_path = Path(tmp_in)
        tmp_out_path = Path(tmp_out)

        for dwg in resolved_dwgs:
            shutil.copy2(dwg, tmp_in_path / dwg.name)

        dxf_paths = dwg_batch_to_dxf(str(tmp_in_path), str(tmp_out_path))
        dxf_by_stem = {Path(path).stem.lower(): path for path in dxf_paths}

        # 先统计总布局数，便于前端进度
        total_layouts = 0
        docs_cache: List[Tuple[Path, Any]] = []
        for dwg in resolved_dwgs:
            dxf_path = dxf_by_stem.get(dwg.stem.lower())
            if not dxf_path:
                logger.warning("未找到DWG对应DXF: %s", str(dwg))
                continue

            doc = ezdxf.readfile(dxf_path)
            docs_cache.append((dwg, doc))
            for layout in doc.layouts:
                if not _is_model_layout(layout.name):
                    total_layouts += 1

        done = 0
        for dwg, doc in docs_cache:
            for layout in doc.layouts:
                layout_name = layout.name
                if _is_model_layout(layout_name):
                    continue

                layout_payload = extract_layout(doc, layout_name, dwg.name)
                if not layout_payload:
                    continue

                json_path = _write_layout_json(out_dir, dwg.stem, layout_payload)
                done += 1

                record = {
                    "dwg_path": str(dwg),
                    "dwg": dwg.name,
                    "layout_name": layout_payload.get("layout_name", layout_name),
                    "sheet_no": layout_payload.get("sheet_no", ""),
                    "sheet_name": layout_payload.get("sheet_name", ""),
                    "json_path": json_path,
                    "data": layout_payload,
                }
                results.append(record)

                if progress_callback:
                    try:
                        progress_callback(
                            {
                                "type": "dwg_progress",
                                "project_id": project_id,
                                "dwg": dwg.name,
                                "layout": layout_name,
                                "done": done,
                                "total": total_layouts,
                            }
                        )
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("DWG进度回调异常: %s", str(exc))

    return results
