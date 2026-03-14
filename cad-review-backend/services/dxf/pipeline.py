"""编排入口 + 缓存 API + 批处理管道。"""

from __future__ import annotations

import json
import logging
import shutil
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import ezdxf

from services.coordinate_service import enrich_json_with_coordinates
from services.dxf.entity_extraction import _extract_dimensions, _extract_insert_info, _extract_pseudo_texts
from services.dxf.geo_utils import _safe_float
from services.dxf.layout_detection import _build_layout_fragments, _detect_layout_frames
from services.dxf.material_extraction import _extract_material_table, _extract_materials
from services.dxf.oda_converter import dwg_batch_to_dxf
from services.dxf.text_utils import (
    _collect_text_entities,
    _display_scale,
    _extract_layout_page_range,
    _extract_sheet_name_from_layout,
    _extract_sheet_no_from_text,
    _is_model_layout,
    _is_sheet_no_like,
    _sanitize_filename,
)
from services.dxf.viewport import (
    _collect_layer_states,
    _collect_viewports,
    _pick_main_viewport,
    calc_model_range,
    get_visible_layers,
)

logger = logging.getLogger(__name__)


def _build_layer_state_snapshot(
    *,
    layout_name: str,
    layers: List[Dict[str, Any]],
    viewports: List[Dict[str, Any]],
) -> Dict[str, Any]:
    visibility = [
        {
            "layer_name": str(item.get("name") or ""),
            "visible": bool(item.get("visible")),
        }
        for item in layers
        if str(item.get("name") or "")
    ]
    overrides: list[dict[str, Any]] = []
    for vp in viewports:
        vp_id = str(vp.get("id") or "")
        for item in vp.get("layer_overrides") or []:
            if not isinstance(item, dict):
                continue
            overrides.append(
                {
                    "viewport_id": vp_id or None,
                    "layer_name": str(item.get("layer_name") or ""),
                    "visible": bool(item.get("visible")),
                    "override_type": str(item.get("override_type") or "vp_freeze"),
                }
            )
    return {
        "layer_state_id": f"LST-{layout_name}",
        "owner_layout_name": layout_name,
        "name": f"{layout_name}_STATE",
        "layer_visibility": visibility,
        "viewport_overrides": overrides,
        "source": "viewport_overrides" if overrides else "layout_embedded_state",
        "confidence": 0.95 if visibility else 0.6,
    }


def _build_z_range_summary(*groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    z_min = None
    z_max = None
    ambiguous_count = 0
    sample_count = 0
    for group in groups:
        for item in group or []:
            if not isinstance(item, dict):
                continue
            low = item.get("z_min")
            high = item.get("z_max")
            if isinstance(low, (int, float)) and isinstance(high, (int, float)):
                sample_count += 1
                z_min = low if z_min is None else min(z_min, low)
                z_max = high if z_max is None else max(z_max, high)
            if bool(item.get("z_ambiguous")):
                ambiguous_count += 1
    return {
        "z_min": round(float(z_min), 3) if z_min is not None else 0.0,
        "z_max": round(float(z_max), 3) if z_max is not None else 0.0,
        "ambiguous_count": ambiguous_count,
        "sample_count": sample_count,
    }


def _collect_text_encoding_evidence(pseudo_texts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    evidence: list[dict[str, Any]] = []
    for item in pseudo_texts:
        if not isinstance(item, dict):
            continue
        encoding = item.get("encoding")
        if not isinstance(encoding, dict):
            continue
        evidence.append(
            {
                "source_entity_id": str(item.get("id") or ""),
                "encoding_detected": encoding.get("encoding_detected"),
                "encoding_confidence": encoding.get("encoding_confidence"),
                "font_name": encoding.get("font_name"),
                "font_substitution": encoding.get("font_substitution"),
                "font_substitution_reason": encoding.get("font_substitution_reason"),
                "ocr_triggered": bool(encoding.get("ocr_triggered")),
                "ocr_fallback": encoding.get("ocr_fallback"),
            }
        )
    return evidence


def render_layout_thumbnail(
    doc,
    layout_name: str,
    output_path: str,
    *,
    dpi: int = 96,
    max_size: int = 2000,
) -> Optional[str]:
    """Render a DXF layout to a black-and-white PNG thumbnail.

    Args:
        doc: ezdxf Document object.
        layout_name: name of the paperspace layout to render.
        output_path: filesystem path for the output PNG.
        dpi: rendering resolution.
        max_size: maximum pixel dimension on longest side.

    Returns:
        output_path on success, None on failure.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from ezdxf.addons.drawing import Frontend, RenderContext
        from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
        from ezdxf.addons.drawing.config import (
            Configuration,
            ColorPolicy,
            BackgroundPolicy,
            HatchPolicy,
            LineweightPolicy,
        )

        layout = doc.layouts.get(layout_name)
        if layout is None:
            logger.warning("render_layout_thumbnail: layout '%s' not found", layout_name)
            return None

        fig = plt.figure(dpi=dpi)
        ax = fig.add_axes([0, 0, 1, 1])

        cfg = Configuration(
            color_policy=ColorPolicy.BLACK,
            custom_fg_color="#000000",
            background_policy=BackgroundPolicy.WHITE,
            custom_bg_color="#ffffff",
            hatch_policy=HatchPolicy.SHOW_OUTLINE,
            lineweight_policy=LineweightPolicy.RELATIVE,
            min_lineweight=0.18,
        )

        ctx = RenderContext(doc)
        backend = MatplotlibBackend(ax)
        frontend = Frontend(ctx, backend, config=cfg)
        frontend.draw_layout(layout, finalize=True)

        ax.set_axis_off()
        fig.set_facecolor("#ffffff")

        fig.savefig(
            output_path,
            dpi=dpi,
            facecolor="#ffffff",
            bbox_inches="tight",
            pad_inches=0.02,
        )
        plt.close(fig)

        from PIL import Image as _PILImage
        with _PILImage.open(output_path) as img:
            w, h = img.size
            if max(w, h) > max_size:
                scale = max_size / max(w, h)
                new_w, new_h = int(w * scale), int(h * scale)
                img = img.resize((new_w, new_h), _PILImage.LANCZOS)
                img.save(output_path, format="PNG")

        logger.info("render_layout_thumbnail OK: %s (%s)", layout_name, output_path)
        return output_path

    except Exception as exc:  # noqa: BLE001
        logger.warning("render_layout_thumbnail failed for '%s': %s", layout_name, exc)
        try:
            import matplotlib.pyplot as _plt
            _plt.close("all")
        except Exception:  # noqa: BLE001
            pass
        return None


def extract_layout(doc, layout_name: str, dwg_filename: str) -> Optional[Dict[str, Any]]:  # noqa: ANN001
    """按单个 Layout 提取 JSON 数据。"""
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

    active_layer = str(getattr(doc.header, "$CLAYER", "") or "")
    viewports = _collect_viewports(doc, layout, model_range, active_layer)
    model_ranges = [vp.get("model_range") for vp in viewports if isinstance(vp.get("model_range"), dict)]

    dimensions = _extract_dimensions(doc, layout, model_range, visible_layers, model_ranges=model_ranges)
    pseudo_texts = _extract_pseudo_texts(doc, layout, model_range, visible_layers, model_ranges=model_ranges)
    insert_entities: List[Dict[str, Any]] = []
    indexes, title_blocks, detail_titles, title_sheet_no, title_sheet_name = _extract_insert_info(
        doc, layout, model_range,
        model_ranges=model_ranges,
        visible_layers=visible_layers,
        capture_inserts=insert_entities,
    )
    materials = _extract_materials(doc, layout, model_range, visible_layers, model_ranges=model_ranges)
    material_table = _extract_material_table(layout)
    layers = _collect_layer_states(doc)
    layer_state_snapshot = _build_layer_state_snapshot(
        layout_name=layout_name,
        layers=layers,
        viewports=viewports,
    )
    layout_page_range = _extract_layout_page_range(layout)
    text_entities = _collect_text_entities(layout)
    text_encoding_evidence = _collect_text_encoding_evidence(pseudo_texts)

    title_no = (title_sheet_no or "").strip()
    layout_no = _extract_sheet_no_from_text(layout_name)
    dwg_no = _extract_sheet_no_from_text(dwg_filename)
    sheet_no = title_no if _is_sheet_no_like(title_no) else (layout_no or dwg_no)
    sheet_name = title_sheet_name or _extract_sheet_name_from_layout(layout_name, sheet_no)

    layout_frames = _detect_layout_frames(
        layout,
        layout_page_range=layout_page_range,
        title_blocks=title_blocks,
        detail_titles=detail_titles,
    )
    layout_fragments = _build_layout_fragments(
        layout_frames,
        title_blocks=title_blocks,
        detail_titles=detail_titles,
        indexes=indexes,
        dimensions=dimensions,
        materials=materials,
        pseudo_texts=pseudo_texts,
        viewports=viewports,
        text_entities=text_entities,
        fallback_sheet_no=sheet_no,
        fallback_sheet_name=sheet_name,
        layout_name=layout_name,
    )

    payload: Dict[str, Any] = {
        "source_dwg": dwg_filename,
        "layout_name": layout_name,
        "sheet_no": sheet_no,
        "sheet_name": sheet_name,
        "extracted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_version": 1,
        "scale": _display_scale(scale),
        "model_range": model_range,
        "layout_page_range": layout_page_range,
        "layout_frames": layout_frames,
        "layout_fragments": layout_fragments,
        "is_multi_sheet_layout": len(layout_fragments) > 1,
        "viewports": viewports,
        "dimensions": dimensions,
        "pseudo_texts": pseudo_texts,
        "insert_entities": insert_entities,
        "indexes": indexes,
        "title_blocks": title_blocks,
        "detail_titles": detail_titles,
        "materials": materials,
        "material_table": material_table,
        "layers": layers,
        "layer_state_snapshot": layer_state_snapshot,
        "text_encoding_evidence": text_encoding_evidence,
        "z_range_summary": _build_z_range_summary(
            dimensions,
            pseudo_texts,
            indexes,
            title_blocks,
            insert_entities,
        ),
        "drawing_register_entry": {
            "sheet_number": sheet_no,
            "title": sheet_name,
            "layout_name": layout_name,
            "sheet_type": "unknown",
        },
    }

    return enrich_json_with_coordinates(payload)


def _convert_dwg_and_extract(dwg_path: str, layout_name: str) -> Optional[Dict[str, Any]]:
    """Single ODA conversion + ezdxf extraction for a DWG/layout pair."""
    source_path = Path(dwg_path).expanduser().resolve()
    if not source_path.exists():
        return None

    with tempfile.TemporaryDirectory(prefix="ccad-layout-extract-") as tmp_root:
        tmp_root_path = Path(tmp_root)
        input_dir = tmp_root_path / "in"
        output_dir = tmp_root_path / "out"
        input_dir.mkdir(parents=True, exist_ok=True)
        output_dir.mkdir(parents=True, exist_ok=True)
        copied = input_dir / source_path.name
        shutil.copy2(source_path, copied)

        dxf_files = dwg_batch_to_dxf(str(input_dir), str(output_dir))
        if not dxf_files:
            return None

        doc = ezdxf.readfile(dxf_files[0])
        return extract_layout(doc, layout_name, source_path.name)


_layout_payload_cache: Dict[Tuple[str, str, float], Optional[Dict[str, Any]]] = {}
_LAYOUT_PAYLOAD_CACHE_MAX = 64


def _get_cached_layout_payload(dwg_path: str, layout_name: str) -> Optional[Dict[str, Any]]:
    """Cache full extract_layout payload keyed by (dwg_path, layout_name, mtime)."""
    source_path = Path(dwg_path).expanduser().resolve()
    if not source_path.exists():
        return None

    try:
        mtime = source_path.stat().st_mtime
    except OSError:
        return None

    cache_key = (str(source_path), layout_name, mtime)
    if cache_key in _layout_payload_cache:
        return _layout_payload_cache[cache_key]

    payload = _convert_dwg_and_extract(str(source_path), layout_name)

    if len(_layout_payload_cache) >= _LAYOUT_PAYLOAD_CACHE_MAX:
        oldest_key = next(iter(_layout_payload_cache))
        del _layout_payload_cache[oldest_key]
    _layout_payload_cache[cache_key] = payload
    return payload


def read_layout_page_range_from_dwg(dwg_path: str, layout_name: str) -> Optional[Dict[str, List[float]]]:
    try:
        payload = _get_cached_layout_payload(dwg_path, layout_name)
    except Exception:  # noqa: BLE001
        return None
    if not payload:
        return None

    page_range = payload.get("layout_page_range") or {}
    mn = page_range.get("min", [0.0, 0.0])
    mx = page_range.get("max", [0.0, 0.0])
    if len(mn) < 2 or len(mx) < 2 or mx[0] <= mn[0] or mx[1] <= mn[1]:
        return None
    return {
        "min": [round(float(mn[0]), 3), round(float(mn[1]), 3)],
        "max": [round(float(mx[0]), 3), round(float(mx[1]), 3)],
    }


def read_layout_indexes_from_dwg(dwg_path: str, layout_name: str) -> Optional[List[Dict[str, Any]]]:
    try:
        payload = _get_cached_layout_payload(dwg_path, layout_name)
    except Exception:  # noqa: BLE001
        return None
    if not payload:
        return None

    indexes: List[Dict[str, Any]] = []
    for index in payload.get("indexes", []) or []:
        position = index.get("position")
        insert_position = index.get("insert_position") or position
        symbol_bbox = index.get("symbol_bbox") or {}
        bbox_min = symbol_bbox.get("min")
        bbox_max = symbol_bbox.get("max")
        if not isinstance(position, list) or len(position) < 2:
            continue
        if not isinstance(insert_position, list) or len(insert_position) < 2:
            continue
        if not isinstance(bbox_min, list) or len(bbox_min) < 2 or not isinstance(bbox_max, list) or len(bbox_max) < 2:
            bbox_min = position
            bbox_max = position
        indexes.append(
            {
                "index_no": str(index.get("index_no") or "").strip(),
                "target_sheet": str(index.get("target_sheet") or "").strip(),
                "position": [round(float(position[0]), 3), round(float(position[1]), 3)],
                "insert_position": [round(float(insert_position[0]), 3), round(float(insert_position[1]), 3)],
                "anchor_source": str(index.get("anchor_source") or "").strip(),
                "symbol_bbox": {
                    "min": [round(float(bbox_min[0]), 3), round(float(bbox_min[1]), 3)],
                    "max": [round(float(bbox_max[0]), 3), round(float(bbox_max[1]), 3)],
                },
            }
        )
    return indexes


def read_layout_detail_titles_from_dwg(dwg_path: str, layout_name: str) -> Optional[List[Dict[str, Any]]]:
    try:
        payload = _get_cached_layout_payload(dwg_path, layout_name)
    except Exception:  # noqa: BLE001
        return None
    if not payload:
        return None

    detail_titles: List[Dict[str, Any]] = []
    for item in payload.get("detail_titles", []) or []:
        position = item.get("position")
        if not isinstance(position, list) or len(position) < 2:
            continue
        title_text = str(item.get("title_text") or "").strip()
        detail_titles.append(
            {
                "label": str(item.get("label") or "").strip(),
                "sheet_no": str(item.get("sheet_no") or "").strip(),
                "title_text": title_text,
                "title_lines": [title_text] if title_text else [],
                "block_name": str(item.get("block_name") or "").strip(),
                "position": [round(float(position[0]), 3), round(float(position[1]), 3)],
                "source": str(item.get("source") or "").strip(),
            }
        )
    return detail_titles


def read_layout_structure_from_dwg(dwg_path: str, layout_name: str) -> Optional[Dict[str, Any]]:
    try:
        payload = _get_cached_layout_payload(dwg_path, layout_name)
    except Exception:  # noqa: BLE001
        return None
    if not payload:
        return None

    return {
        "sheet_no": payload.get("sheet_no"),
        "sheet_name": payload.get("sheet_name"),
        "layout_frames": payload.get("layout_frames") or [],
        "layout_fragments": payload.get("layout_fragments") or [],
        "is_multi_sheet_layout": bool(payload.get("is_multi_sheet_layout")),
    }


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
    thumbnail_dir: Optional[str] = None,
    dxf_dir: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """批量处理DWG：ODA批量转DXF + ezdxf按布局提取JSON。

    Args:
        thumbnail_dir: 已废弃，保留参数兼容旧调用，不再渲染缩略图。
        dxf_dir: 若提供，则将 DXF 文件复制到该目录持久保存，供后续按需渲染缩略图。
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

        # 如果指定了 dxf_dir，把 DXF 文件持久化保存，供后续按需渲染缩略图
        persistent_dxf_by_stem: Dict[str, str] = {}
        if dxf_dir:
            dxf_persist_dir = Path(dxf_dir)
            dxf_persist_dir.mkdir(parents=True, exist_ok=True)
            for stem, src_path in dxf_by_stem.items():
                dst = dxf_persist_dir / Path(src_path).name
                shutil.copy2(src_path, dst)
                persistent_dxf_by_stem[stem] = str(dst)

        total_layouts = 0
        docs_cache: List[Tuple[Path, Any, str]] = []
        for dwg in resolved_dwgs:
            dxf_path = dxf_by_stem.get(dwg.stem.lower())
            if not dxf_path:
                logger.warning("未找到DWG对应DXF: %s", str(dwg))
                continue

            persistent_dxf = persistent_dxf_by_stem.get(dwg.stem.lower(), "")
            doc = ezdxf.readfile(dxf_path)
            docs_cache.append((dwg, doc, persistent_dxf))
            for layout in doc.layouts:
                if not _is_model_layout(layout.name):
                    total_layouts += 1

        done = 0
        for dwg, doc, persistent_dxf in docs_cache:
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
                    "thumbnail_path": None,   # 由调用方按需渲染（仅对未匹配布局）
                    "dxf_path": persistent_dxf,  # 持久化 DXF 路径，供后续缩略图渲染
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
