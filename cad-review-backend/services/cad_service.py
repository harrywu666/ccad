"""
CAD 数据提取服务（新路线）
技术方案：ODA File Converter + ezdxf
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from services.dxf_service import (
    _extract_sheet_name_from_layout,
    _extract_sheet_no_from_text,
    _is_model_layout,
    _sanitize_filename,
    process_dwg_files,
)

logger = logging.getLogger(__name__)


def _default_layout_payload(dwg_name: str, layout_name: str, sheet_no: str, sheet_name: str) -> Dict[str, Any]:
    return {
        "source_dwg": f"{dwg_name}.dwg",
        "layout_name": layout_name,
        "sheet_no": sheet_no,
        "sheet_name": sheet_name,
        "extracted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_version": 1,
        "scale": "",
        "model_range": {"min": [0.0, 0.0], "max": [0.0, 0.0]},
        "viewports": [],
        "dimensions": [],
        "pseudo_texts": [],
        "indexes": [],
        "title_blocks": [],
        "materials": [],
        "material_table": [],
        "layers": [],
    }


def _to_layout_info(payload: Dict[str, Any], json_path: str) -> Dict[str, Any]:
    return {
        "source_dwg": payload.get("source_dwg", ""),
        "layout_name": payload.get("layout_name", ""),
        "sheet_no": payload.get("sheet_no", ""),
        "sheet_name": payload.get("sheet_name", ""),
        "json_path": json_path,
        "viewports": payload.get("viewports") or [],
        "dimensions": payload.get("dimensions") or [],
        "pseudo_texts": payload.get("pseudo_texts") or [],
        "indexes": payload.get("indexes") or [],
        "title_blocks": payload.get("title_blocks") or [],
        "detail_titles": payload.get("detail_titles") or [],
        "materials": payload.get("materials") or [],
        "material_table": payload.get("material_table") or [],
        "layers": payload.get("layers") or [],
        "layout_frames": payload.get("layout_frames") or [],
        "layout_fragments": payload.get("layout_fragments") or [],
        "is_multi_sheet_layout": bool(payload.get("is_multi_sheet_layout")),
        "data": payload,
    }


def _mock_layout_specs_from_env() -> List[Dict[str, str]]:
    raw = os.getenv("CAD_MOCK_LAYOUTS", "").strip()
    if not raw:
        return []

    specs: List[Dict[str, str]] = []
    for seg in raw.split(","):
        token = seg.strip()
        if not token:
            continue
        if "|" in token:
            sheet_no, layout_name = token.split("|", 1)
        else:
            sheet_no, layout_name = token, token
        specs.append({"sheet_no": sheet_no.strip(), "layout_name": layout_name.strip()})
    return specs


def _write_mock_layout_json(output_dir: Path, dwg_name: str, layout_name: str, sheet_no: str) -> Dict[str, Any]:
    payload = _default_layout_payload(
        dwg_name=dwg_name,
        layout_name=layout_name,
        sheet_no=sheet_no,
        sheet_name=_extract_sheet_name_from_layout(layout_name, sheet_no),
    )
    payload["dimensions"] = [
        {
            "id": "dim_001",
            "value": 2400,
            "display_text": "2400",
            "layer": "S-DIMS",
            "source": "model_space",
            "defpoint": [0.0, 0.0],
            "defpoint2": [2400.0, 0.0],
            "text_position": [1200.0, 300.0],
            "global_pct": {"x": 12.0, "y": 70.0},
            "grid": "C12",
            "in_quadrants": {"图2左上": {"local_x_pct": 20.0, "local_y_pct": 80.0}},
        }
    ]
    payload["indexes"] = [
        {
            "id": "idx_001",
            "index_no": "①",
            "target_sheet": "A2-01",
            "source": "layout_space",
            "position": [5600.0, 2300.0],
        }
    ]

    file_name = f"{dwg_name}_{_sanitize_filename(layout_name)}.json"
    json_path = output_dir / file_name
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return _to_layout_info(payload, str(json_path))


def mock_extract_dwg_data(dwg_path: str, output_dir: str) -> List[Dict[str, Any]]:
    dwg_name = Path(dwg_path).stem
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    specs = _mock_layout_specs_from_env()
    if not specs:
        base_no = _extract_sheet_no_from_text(dwg_name) or dwg_name
        specs = [
            {"sheet_no": base_no, "layout_name": f"{base_no} 平面布置图"},
            {"sheet_no": f"{base_no}a", "layout_name": f"{base_no}a 立面图"},
        ]

    result: List[Dict[str, Any]] = []
    for spec in specs:
        layout_name = spec.get("layout_name", "").strip()
        if not layout_name or _is_model_layout(layout_name):
            continue

        sheet_no = spec.get("sheet_no", "").strip() or _extract_sheet_no_from_text(layout_name)
        result.append(_write_mock_layout_json(out_dir, dwg_name, layout_name, sheet_no))

    logger.info("Mock DWG提取完成: dwg=%s layouts=%s", dwg_name, len(result))
    return result


def extract_dwg_data(dwg_path: str, output_dir: str) -> List[Dict[str, Any]]:
    """
    单DWG提取（对外兼容接口）。
    """
    result_map = extract_dwg_batch_data([dwg_path], output_dir)
    key = str(Path(dwg_path).resolve())
    return result_map.get(key, [])


def extract_dwg_batch_data(dwg_paths: Iterable[str], output_dir: str, thumbnail_dir: Optional[str] = None, dxf_dir: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    """
    批量提取DWG布局数据。
    返回：{dwg_path: [layout_json_info, ...]}

    Args:
        thumbnail_dir: 已废弃，不再于提取阶段渲染缩略图。
        dxf_dir: 若提供，DXF 文件将复制到该目录，供后续按需渲染缩略图（仅对未匹配布局）。
    """
    resolved_paths = [str(Path(path).resolve()) for path in dwg_paths if str(path).strip()]
    result_map: Dict[str, List[Dict[str, Any]]] = {path: [] for path in resolved_paths}
    if not resolved_paths:
        return result_map

    out_dir = Path(output_dir).expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    force_mock = os.getenv("CAD_FORCE_MOCK", "").strip() == "1"
    if force_mock or os.getenv("CAD_MOCK_LAYOUTS", "").strip():
        for path in resolved_paths:
            result_map[path] = mock_extract_dwg_data(path, str(out_dir))
        return result_map

    try:
        records = process_dwg_files(
            dwg_paths=resolved_paths,
            project_id="",
            output_dir=str(out_dir),
            progress_callback=None,
            dxf_dir=dxf_dir,
        )

        for record in records:
            key = str(Path(record.get("dwg_path", "")).resolve())
            if key not in result_map:
                continue

            payload = record.get("data") or {}
            info = _to_layout_info(payload, str(record.get("json_path", "")))
            info["thumbnail_path"] = None          # 未匹配时由 ingest_service 按需填充
            info["dxf_path"] = record.get("dxf_path")  # 持久化 DXF 路径
            if not _is_model_layout(info.get("layout_name", "")):
                result_map[key].append(info)

        for path in resolved_paths:
            logger.info("DWG提取完成: dwg=%s layouts=%s", Path(path).name, len(result_map[path]))

    except Exception as exc:  # noqa: BLE001
        allow_mock_fallback = os.getenv("CAD_FORCE_MOCK", "").strip() == "1" or os.getenv("CAD_MOCK_FALLBACK", "").strip() == "1"
        if allow_mock_fallback:
            logger.warning("DXF提取失败，回退mock（CAD_MOCK_FALLBACK=1）: %s", str(exc))
            for path in resolved_paths:
                result_map[path] = mock_extract_dwg_data(path, str(out_dir))
        else:
            logger.error("DXF提取失败: %s", str(exc))
            raise RuntimeError(f"DWG提取失败，请检查ODA File Converter是否正确安装: {exc}") from exc

    return result_map
