"""
CAD数据提取服务模块
负责调用CAD插件提取DWG中的布局数据（一个布局一个JSON）
"""

from __future__ import annotations

import json
import logging
import os
import platform
import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List

logger = logging.getLogger(__name__)


MODEL_LAYOUT_NAMES = {
    "model",
    "modelspace",
    "model_space",
    "模型",
    "模型空间",
}


def _normalize_layout_name(name: str) -> str:
    return re.sub(r"[\s\-_./\\()（）【】\[\]{}]+", "", (name or "").strip().lower())


def _is_model_layout(layout_name: str) -> bool:
    norm = _normalize_layout_name(layout_name)
    return norm in MODEL_LAYOUT_NAMES


def _sanitize_filename(value: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", value).strip("_") or "layout"


def _extract_sheet_no_from_text(text: str) -> str:
    if not text:
        return ""

    patterns = [
        r"[A-Za-z]{1,3}\d{0,2}[.\-_]\d{1,3}[a-zA-Z]?",
        r"[A-Za-z]\d{1,3}[a-zA-Z]?",
        r"\d{2}\.\d{2}[a-zA-Z]?",
    ]
    for pattern in patterns:
        m = re.search(pattern, text)
        if m:
            return m.group(0)
    return ""


def _extract_sheet_name_from_layout(layout_name: str, sheet_no: str) -> str:
    if not layout_name:
        return ""
    if not sheet_no:
        return layout_name.strip()
    return layout_name.replace(sheet_no, "", 1).strip(" -_:.|")


def _default_layout_payload(dwg_name: str, layout_name: str, sheet_no: str, sheet_name: str) -> Dict[str, Any]:
    return {
        "source_dwg": f"{dwg_name}.dwg",
        "layout_name": layout_name,
        "sheet_no": sheet_no,
        "sheet_name": sheet_name,
        "extracted_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "data_version": 1,
        "scale": "1:100",
        "model_range": {"min": [0.0, 0.0], "max": [10000.0, 8000.0]},
        "viewports": [],
        "dimensions": [],
        "pseudo_texts": [],
        "indexes": [],
        "title_blocks": [],
        "materials": [],
        "material_table": [],
        "layers": [],
    }


def _normalize_layout_payload(data: Dict[str, Any], dwg_name: str) -> Dict[str, Any]:
    layout_name = str(data.get("layout_name") or data.get("layout") or "").strip()
    sheet_no = str(data.get("sheet_no") or "").strip()
    sheet_name = str(data.get("sheet_name") or "").strip()

    if not sheet_no:
        sheet_no = _extract_sheet_no_from_text(layout_name)
    if not sheet_name:
        sheet_name = _extract_sheet_name_from_layout(layout_name, sheet_no)

    payload = _default_layout_payload(dwg_name, layout_name or "layout", sheet_no, sheet_name)
    payload.update(data)
    payload["source_dwg"] = str(data.get("source_dwg") or f"{dwg_name}.dwg")
    payload["layout_name"] = layout_name or payload["layout_name"]
    payload["sheet_no"] = str(payload.get("sheet_no") or sheet_no)
    payload["sheet_name"] = str(payload.get("sheet_name") or sheet_name)
    payload["viewports"] = payload.get("viewports") or []
    payload["dimensions"] = payload.get("dimensions") or []
    payload["pseudo_texts"] = payload.get("pseudo_texts") or []
    payload["indexes"] = payload.get("indexes") or []
    payload["title_blocks"] = payload.get("title_blocks") or []
    payload["materials"] = payload.get("materials") or []
    payload["material_table"] = payload.get("material_table") or []
    payload["layers"] = payload.get("layers") or []
    return payload


def _parse_layout_json(json_path: Path, dwg_name: str) -> Dict[str, Any]:
    try:
        raw = json.loads(json_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        logger.warning("读取布局JSON失败: %s (%s)", str(json_path), str(exc))
        return {}

    if not isinstance(raw, dict):
        logger.warning("布局JSON格式非法(非对象): %s", str(json_path))
        return {}

    payload = _normalize_layout_payload(raw, dwg_name)
    layout_name = payload.get("layout_name", "")
    if _is_model_layout(layout_name):
        logger.info("跳过Model布局JSON: %s", str(json_path))
        return {}

    return {
        "source_dwg": payload.get("source_dwg", f"{dwg_name}.dwg"),
        "layout_name": layout_name,
        "sheet_no": payload.get("sheet_no", ""),
        "sheet_name": payload.get("sheet_name", ""),
        "json_path": str(json_path),
        "viewports": payload.get("viewports", []),
        "dimensions": payload.get("dimensions", []),
        "pseudo_texts": payload.get("pseudo_texts", []),
        "indexes": payload.get("indexes", []),
        "title_blocks": payload.get("title_blocks", []),
        "materials": payload.get("materials", []),
        "material_table": payload.get("material_table", []),
        "layers": payload.get("layers", []),
    }


def _collect_layout_jsons(dwg_path: str, output_dir: str) -> List[Dict[str, Any]]:
    """
    收集插件输出的布局JSON文件并归一化
    优先规则：
    1. {output_dir}/{dwg_stem}_*.json
    2. {output_dir}/{dwg_stem}/*.json
    """
    dwg_name = Path(dwg_path).stem
    out_dir = Path(output_dir)
    candidates = []

    candidates.extend(sorted(out_dir.glob(f"{dwg_name}_*.json")))

    nested_dir = out_dir / dwg_name
    if nested_dir.exists():
        candidates.extend(sorted(nested_dir.glob("*.json")))

    seen = set()
    parsed: List[Dict[str, Any]] = []
    for json_file in candidates:
        key = str(json_file.resolve())
        if key in seen:
            continue
        seen.add(key)

        info = _parse_layout_json(json_file, dwg_name)
        if info:
            parsed.append(info)

    parsed.sort(key=lambda item: (item.get("layout_name", ""), item.get("sheet_no", "")))
    return parsed


def _mock_layout_specs_from_env(dwg_name: str) -> List[Dict[str, str]]:
    """
    通过环境变量定义mock布局，方便本地联调：
    CAD_MOCK_LAYOUTS='A1.01|平面布置图,A1.02|天花布置图'
    """
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
        specs.append(
            {
                "sheet_no": sheet_no.strip(),
                "layout_name": layout_name.strip(),
            }
        )

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
        }
    ]

    file_name = f"{dwg_name}_{_sanitize_filename(layout_name)}.json"
    json_path = output_dir / file_name
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return _parse_layout_json(json_path, dwg_name)


def mock_extract_dwg_data(dwg_path: str, output_dir: str) -> List[Dict[str, Any]]:
    """
    Mock数据提取（用于非Windows开发环境）：
    规则与真实逻辑一致：一个布局输出一个JSON
    """
    dwg_name = Path(dwg_path).stem
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    specs = _mock_layout_specs_from_env(dwg_name)
    if not specs:
        base_no = _extract_sheet_no_from_text(dwg_name) or dwg_name
        specs = [
            {"sheet_no": base_no, "layout_name": f"{base_no} 平面布置图"},
            {"sheet_no": f"{base_no}a", "layout_name": f"{base_no}a 立面图"},
        ]

    results = []
    for spec in specs:
        layout_name = spec.get("layout_name", "").strip()
        if not layout_name or _is_model_layout(layout_name):
            continue
        sheet_no = spec.get("sheet_no", "").strip() or _extract_sheet_no_from_text(layout_name)
        info = _write_mock_layout_json(out_dir, dwg_name, layout_name, sheet_no)
        if info:
            results.append(info)

    logger.info("Mock DWG提取完成: dwg=%s layouts=%s", dwg_name, len(results))
    return results


def real_extract_dwg_data(dwg_path: str, output_dir: str) -> List[Dict[str, Any]]:
    """
    真实DWG数据提取（Windows + AutoCAD插件）
    插件调用约定：
    - 可配置 CAD_PLUGIN_EXTRACTOR_CMD
    - 命令模板可含 {dwg} 和 {outdir} 占位符
    - 插件执行后在 output_dir 下写入 {dwg_stem}_*.json
    """
    cmd_template = os.getenv("CAD_PLUGIN_EXTRACTOR_CMD", "").strip()
    if cmd_template:
        cmd = cmd_template.format(dwg=dwg_path, outdir=output_dir)
        logger.info("执行CAD插件命令: %s", cmd)
        proc = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(f"CAD插件执行失败: rc={proc.returncode}, stderr={proc.stderr[:500]}")
        if proc.stdout.strip():
            logger.info("CAD插件输出: %s", proc.stdout.strip()[:500])
    else:
        from services.autocad_com_service import extract_multiple_dwgs_with_com

        logger.info("未配置 CAD_PLUGIN_EXTRACTOR_CMD，改用内置AutoCAD COM自动化")
        extract_multiple_dwgs_with_com([dwg_path], output_dir)

    results = _collect_layout_jsons(dwg_path, output_dir)
    logger.info("真实DWG提取收集完成: dwg=%s layouts=%s", Path(dwg_path).name, len(results))
    return results


def extract_dwg_data(dwg_path: str, output_dir: str) -> List[Dict[str, Any]]:
    """
    提取DWG布局数据（一个布局 = 一个JSON）
    """
    if platform.system() != "Windows":
        return mock_extract_dwg_data(dwg_path, output_dir)

    try:
        return real_extract_dwg_data(dwg_path, output_dir)
    except Exception as exc:  # noqa: BLE001
        logger.warning("真实DWG提取失败，回退mock: %s", str(exc))
        return mock_extract_dwg_data(dwg_path, output_dir)


def extract_dwg_batch_data(dwg_paths: Iterable[str], output_dir: str) -> Dict[str, List[Dict[str, Any]]]:
    """
    批量提取DWG布局数据。
    返回：{dwg_path: [layout_json_info, ...]}
    """
    resolved_paths = [str(Path(p).resolve()) for p in dwg_paths if str(p).strip()]
    result_map: Dict[str, List[Dict[str, Any]]] = {p: [] for p in resolved_paths}
    if not resolved_paths:
        return result_map

    if platform.system() != "Windows":
        for p in resolved_paths:
            result_map[p] = mock_extract_dwg_data(p, output_dir)
        return result_map

    cmd_template = os.getenv("CAD_PLUGIN_EXTRACTOR_CMD", "").strip()
    if cmd_template:
        for p in resolved_paths:
            try:
                result_map[p] = real_extract_dwg_data(p, output_dir)
            except Exception as exc:  # noqa: BLE001
                logger.warning("DWG提取失败(回退mock): %s (%s)", p, str(exc))
                result_map[p] = mock_extract_dwg_data(p, output_dir)
        return result_map

    try:
        from services.autocad_com_service import extract_multiple_dwgs_with_com

        extract_multiple_dwgs_with_com(resolved_paths, output_dir)
        for p in resolved_paths:
            result_map[p] = _collect_layout_jsons(p, output_dir)
            if not result_map[p]:
                logger.warning("COM未产出布局JSON，回退mock: %s", p)
                result_map[p] = mock_extract_dwg_data(p, output_dir)
    except Exception as exc:  # noqa: BLE001
        logger.warning("批量COM提取失败，全部回退mock: %s", str(exc))
        for p in resolved_paths:
            result_map[p] = mock_extract_dwg_data(p, output_dir)

    return result_map
