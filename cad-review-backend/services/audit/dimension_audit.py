"""Dimension audit implementation."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from domain.sheet_normalization import normalize_index_no, normalize_sheet_no
from models import AuditResult, Drawing, JsonData, Project
from services.ai_prompt_service import resolve_stage_system_prompt
from services.audit.common import build_anchor, to_evidence_json
from services.audit.image_pipeline import pdf_page_to_5images
from services.audit.persistence import add_and_commit
from services.audit.prompt_builder import (
    build_pair_compare_prompt,
    build_single_sheet_prompt,
    compact_dimensions,
)
from services.audit.result_parser import parse_dimension_pair_item
from services.coordinate_service import cad_to_global_pct, enrich_json_with_coordinates
from services.storage_path_service import resolve_project_dir

logger = logging.getLogger(__name__)


# 功能说明：读取JSON文件内容
def _read_json(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


# 功能说明：在PNG目录中查找对应的PDF文件
def _find_pdf_in_png_dir(png_path: str) -> Optional[str]:
    if not png_path:
        return None
    try:
        folder = Path(png_path).expanduser().resolve().parent
    except Exception:
        return None
    if not folder.exists() or not folder.is_dir():
        return None
    pdfs = sorted(folder.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not pdfs:
        return None
    return str(pdfs[0])


# 功能说明：收集图纸页面的资产映射信息
def _collect_page_asset_map(rows: List[Drawing]) -> Dict[str, Dict[str, Any]]:
    asset_map: Dict[str, Dict[str, Any]] = {}
    by_key: Dict[str, List[Drawing]] = defaultdict(list)
    for row in rows:
        if not row.sheet_no:
            continue
        by_key[normalize_sheet_no(row.sheet_no)].append(row)
    for key, items in by_key.items():
        items_sorted = sorted(
            items,
            key=lambda x: (x.data_version or 0, 1 if x.status == "matched" else 0),
            reverse=True,
        )
        latest = items_sorted[0]
        asset_map[key] = {
            "png_path": latest.png_path,
            "page_index": latest.page_index,
            "pdf_path": _find_pdf_in_png_dir(latest.png_path or ""),
        }
    return asset_map


# 功能说明：获取尺寸标注的全局坐标点
def _dimension_global_point(
    dim: Dict[str, Any], model_range: Dict[str, Any]
) -> Optional[Dict[str, float]]:
    gp = dim.get("global_pct")
    if isinstance(gp, dict) and gp.get("x") is not None and gp.get("y") is not None:
        try:
            return {"x": float(gp["x"]), "y": float(gp["y"])}
        except (TypeError, ValueError):
            pass
    pos = dim.get("text_position") or dim.get("defpoint")
    if not isinstance(pos, (list, tuple)) or len(pos) < 2:
        return None
    try:
        x = float(pos[0])
        y = float(pos[1])
    except (TypeError, ValueError):
        return None
    pct_x, pct_y = cad_to_global_pct(x, y, model_range or {})
    return {"x": pct_x, "y": pct_y}


# 功能说明：从环境变量读取整数配置，带范围限制
def _read_int_env(name: str, default: int, *, low: int = 1, high: int = 64) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(low, min(high, value))


# 功能说明：将值序列化为规范的JSON字符串
def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


# 功能说明：计算多个字符串的SHA256哈希值
def _sha256_parts(parts: List[str]) -> str:
    digest = hashlib.sha256()
    for part in parts:
        digest.update((part or "").encode("utf-8", errors="ignore"))
        digest.update(b"\n")
    return digest.hexdigest()


# 功能说明：获取文件签名（路径、大小、修改时间）
def _file_sig(path: Optional[str]) -> str:
    if not path:
        return "missing"
    p = Path(path).expanduser()
    if not p.exists():
        return f"missing:{path}"
    st = p.stat()
    return f"{p.resolve()}|{st.st_size}|{int(st.st_mtime)}"


# 功能说明：获取项目的缓存目录路径
def _cache_dir_for_project(project: Project) -> Path:
    root = resolve_project_dir(project, ensure=True) / "cache" / "dimension-v1"
    root.mkdir(parents=True, exist_ok=True)
    return root


# 功能说明：生成缓存文件的完整路径
def _cache_file(cache_dir: Path, prefix: str, key: str) -> Path:
    return cache_dir / f"{prefix}_{key}.json"


# 功能说明：从缓存加载列表数据
def _load_cached_list(
    cache_dir: Path, prefix: str, key: str
) -> Optional[List[Dict[str, Any]]]:
    file_path = _cache_file(cache_dir, prefix, key)
    if not file_path.exists():
        return None
    try:
        payload = json.loads(file_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return None


# 功能说明：保存JSON数据到缓存
def _save_cache_json(cache_dir: Path, prefix: str, key: str, payload: Any) -> None:
    file_path = _cache_file(cache_dir, prefix, key)
    tmp_path = file_path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(file_path)


# 功能说明：按图纸加载JSON数据
def _load_json_by_sheet(project_id: str, db) -> Dict[str, Dict[str, Any]]:
    json_rows = (
        db.query(JsonData)
        .filter(
            JsonData.project_id == project_id,
            JsonData.is_latest == 1,
        )
        .all()
    )

    json_by_sheet: Dict[str, Dict[str, Any]] = {}
    for row in json_rows:
        if not row.json_path or not row.sheet_no:
            continue
        try:
            payload = _read_json(row.json_path)
        except Exception:
            continue
        enriched = enrich_json_with_coordinates(payload)
        key = normalize_sheet_no(row.sheet_no)
        if not key:
            continue
        json_by_sheet[key] = {
            "row": row,
            "sheet_no": row.sheet_no,
            "sheet_name": payload.get("sheet_name") or payload.get("layout_name") or "",
            "dimensions": enriched.get("dimensions", []) or [],
            "indexes": enriched.get("indexes", []) or [],
            "model_range": enriched.get("model_range") or {},
        }
    return json_by_sheet


# 功能说明：加载项目的图纸资产信息
def _load_drawing_assets(project_id: str, db) -> Dict[str, Dict[str, Any]]:
    drawing_rows = (
        db.query(Drawing)
        .filter(
            Drawing.project_id == project_id,
            Drawing.replaced_at == None,
        )
        .all()
    )
    return _collect_page_asset_map(drawing_rows)


# 功能说明：构建需要对比的图纸对
def _build_pairs(
    json_by_sheet: Dict[str, Dict[str, Any]],
    pair_filters: Optional[List[Tuple[str, str]]],
) -> List[Dict[str, str]]:
    pair_keys = set()
    pairs: List[Dict[str, str]] = []

    if pair_filters is not None:
        requested_pairs = {
            tuple(sorted([normalize_sheet_no(a), normalize_sheet_no(b)]))
            for a, b in pair_filters
            if normalize_sheet_no(a)
            and normalize_sheet_no(b)
            and normalize_sheet_no(a) != normalize_sheet_no(b)
        }
        for a_key, b_key in sorted(requested_pairs):
            if a_key not in json_by_sheet or b_key not in json_by_sheet:
                continue
            pair_key = tuple(sorted([a_key, b_key]))
            if pair_key in pair_keys:
                continue
            pair_keys.add(pair_key)
            pairs.append({"a": a_key, "b": b_key})
        return pairs

    for src_key, src in json_by_sheet.items():
        for idx in src["indexes"]:
            target_raw = str(idx.get("target_sheet", "") or "").strip()
            tgt_key = normalize_sheet_no(target_raw)
            if not tgt_key or tgt_key not in json_by_sheet or tgt_key == src_key:
                continue
            pair_key = tuple(sorted([src_key, tgt_key]))
            if pair_key in pair_keys:
                continue
            pair_keys.add(pair_key)
            pairs.append({"a": src_key, "b": tgt_key})
    return pairs


# 功能说明：准备图纸语义分析输入数据
def _prepare_sheet_semantic_inputs(
    json_by_sheet: Dict[str, Dict[str, Any]],
    page_assets_by_sheet: Dict[str, Dict[str, Any]],
    pairs: List[Dict[str, str]],
    prompt_version: str,
    cache_dir: Path,
    audit_version: int,
) -> Tuple[
    Dict[str, List[Dict[str, Any]]],
    Dict[str, str],
    List[Dict[str, Any]],
    int,
    int,
    int,
]:
    semantic_cache: Dict[str, List[Dict[str, Any]]] = {}
    semantic_hashes: Dict[str, str] = {}
    sheet_jobs: List[Dict[str, Any]] = []
    involved = {p["a"] for p in pairs} | {p["b"] for p in pairs}
    sheet_cache_hit = 0
    sheet_cache_miss = 0

    for sheet_key in sorted(involved):
        sheet = json_by_sheet[sheet_key]
        dims = sheet["dimensions"]
        if not dims:
            semantic_cache[sheet_key] = []
            semantic_hashes[sheet_key] = _sha256_parts([sheet_key, "empty"])
            continue

        for dim in dims:
            if dim.get("global_pct") is None:
                point = _dimension_global_point(dim, sheet["model_range"])
                if point:
                    dim["global_pct"] = point

        dimension_lookup: Dict[str, Dict[str, Any]] = {}
        for dim in dims:
            dim_id = str(dim.get("id") or "").strip()
            if not dim_id:
                continue
            dim_key = normalize_index_no(dim_id)
            if dim_key and dim_key not in dimension_lookup:
                dimension_lookup[dim_key] = dim
        sheet["dimension_lookup"] = dimension_lookup

        page_asset = page_assets_by_sheet.get(sheet_key)
        if not page_asset:
            raise RuntimeError(
                f"尺寸核对缺少图纸资产：{sheet['sheet_no']} 未找到对应图像/页码。"
            )
        pdf_path = page_asset.get("pdf_path")
        page_index = page_asset.get("page_index")
        if not pdf_path or page_index is None:
            raise RuntimeError(
                f"尺寸核对缺少PDF页定位：{sheet['sheet_no']} pdf_path={pdf_path} page_index={page_index}"
            )

        dims_compact = compact_dimensions(dims)
        prompt = build_single_sheet_prompt(
            sheet_no=sheet["sheet_no"],
            sheet_name=sheet["sheet_name"],
            dims_compact=dims_compact,
        )
        sheet_cache_key = _sha256_parts(
            [
                prompt_version,
                "sheet_semantic",
                str(audit_version),
                sheet_key,
                sheet["sheet_no"] or "",
                str(page_index),
                _file_sig(str(pdf_path)),
                _canonical_json(dims_compact),
            ]
        )

        cached_semantic = _load_cached_list(cache_dir, "sheet", sheet_cache_key)
        if cached_semantic is not None:
            semantic_cache[sheet_key] = cached_semantic
            semantic_hashes[sheet_key] = _sha256_parts(
                [sheet_cache_key, _canonical_json(cached_semantic)]
            )
            sheet_cache_hit += 1
            continue

        sheet_jobs.append(
            {
                "sheet_key": sheet_key,
                "sheet_no": sheet["sheet_no"],
                "pdf_path": str(pdf_path),
                "page_index": int(page_index),
                "prompt": prompt,
                "cache_key": sheet_cache_key,
            }
        )
        sheet_cache_miss += 1

    return (
        semantic_cache,
        semantic_hashes,
        sheet_jobs,
        sheet_cache_hit,
        sheet_cache_miss,
        len(involved),
    )


# 功能说明：异步执行图纸语义分析任务
async def _execute_sheet_jobs(
    sheet_jobs: List[Dict[str, Any]],
    sheet_concurrency: int,
    cache_dir: Path,
    call_kimi,
) -> List[Tuple[str, List[Dict[str, Any]], str]]:
    if not sheet_jobs:
        return []

    async def _run_sheet_job(
        job: Dict[str, Any],
    ) -> Tuple[str, List[Dict[str, Any]], str]:
        images = await asyncio.to_thread(
            pdf_page_to_5images,
            job["pdf_path"],
            job["page_index"],
            0.20,
        )
        semantic_result = await call_kimi(
            system_prompt=resolve_stage_system_prompt("dimension_single_sheet"),
            user_prompt=job["prompt"],
            images=[
                images["full"],
                images["top_left"],
                images["top_right"],
                images["bottom_left"],
                images["bottom_right"],
            ],
            temperature=0.0,
        )
        if not isinstance(semantic_result, list):
            raise RuntimeError(
                f"尺寸语义分析返回格式异常：{job['sheet_no']}，返回类型={type(semantic_result).__name__}"
            )
        cleaned = [item for item in semantic_result if isinstance(item, dict)]
        await asyncio.to_thread(
            _save_cache_json, cache_dir, "sheet", job["cache_key"], cleaned
        )
        return job["sheet_key"], cleaned, job["cache_key"]

    semaphore = asyncio.Semaphore(sheet_concurrency)

    async def _worker(job: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]], str]:
        async with semaphore:
            return await _run_sheet_job(job)

    results = await asyncio.gather(
        *[_worker(job) for job in sheet_jobs], return_exceptions=True
    )
    final_results: List[Tuple[str, List[Dict[str, Any]], str]] = []
    for result in results:
        if isinstance(result, Exception):
            raise result
        final_results.append(result)
    return final_results


# 功能说明：准备图纸对比输入数据
def _prepare_pair_compare_inputs(
    pairs: List[Dict[str, str]],
    json_by_sheet: Dict[str, Dict[str, Any]],
    semantic_cache: Dict[str, List[Dict[str, Any]]],
    semantic_hashes: Dict[str, str],
    prompt_version: str,
    cache_dir: Path,
    audit_version: int,
) -> Tuple[Dict[Tuple[str, str], List[Dict[str, Any]]], List[Dict[str, Any]], int, int]:
    pair_compare_results: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    pair_jobs: List[Dict[str, Any]] = []
    pair_cache_hit = 0
    pair_cache_miss = 0

    for pair in pairs:
        a = json_by_sheet[pair["a"]]
        b = json_by_sheet[pair["b"]]
        semantic_a = semantic_cache.get(pair["a"], [])
        semantic_b = semantic_cache.get(pair["b"], [])
        if not semantic_a or not semantic_b:
            continue

        pair_cache_key = _sha256_parts(
            [
                prompt_version,
                "pair_compare",
                str(audit_version),
                pair["a"],
                pair["b"],
                semantic_hashes.get(pair["a"], ""),
                semantic_hashes.get(pair["b"], ""),
            ]
        )
        cached_compare = _load_cached_list(cache_dir, "pair", pair_cache_key)
        if cached_compare is not None:
            pair_compare_results[(pair["a"], pair["b"])] = cached_compare
            pair_cache_hit += 1
            continue

        pair_jobs.append(
            {
                "a_key": pair["a"],
                "b_key": pair["b"],
                "a_sheet_no": a["sheet_no"],
                "a_sheet_name": a["sheet_name"],
                "b_sheet_no": b["sheet_no"],
                "b_sheet_name": b["sheet_name"],
                "semantic_a": semantic_a,
                "semantic_b": semantic_b,
                "cache_key": pair_cache_key,
            }
        )
        pair_cache_miss += 1

    return pair_compare_results, pair_jobs, pair_cache_hit, pair_cache_miss


# 功能说明：异步执行图纸对比任务
async def _execute_pair_jobs(
    pair_jobs: List[Dict[str, Any]],
    pair_concurrency: int,
    cache_dir: Path,
    call_kimi,
) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    if not pair_jobs:
        return {}

    async def _run_pair_job(
        job: Dict[str, Any],
    ) -> Tuple[Tuple[str, str], List[Dict[str, Any]]]:
        compare_result = await call_kimi(
            system_prompt=resolve_stage_system_prompt("dimension_pair_compare"),
            user_prompt=build_pair_compare_prompt(
                a_sheet_no=job["a_sheet_no"],
                a_sheet_name=job["a_sheet_name"],
                a_semantic=job["semantic_a"],
                b_sheet_no=job["b_sheet_no"],
                b_sheet_name=job["b_sheet_name"],
                b_semantic=job["semantic_b"],
            ),
            temperature=0.0,
        )
        if not isinstance(compare_result, list):
            raise RuntimeError(
                f"尺寸图对比对返回格式异常：{job['a_sheet_no']} vs {job['b_sheet_no']}，"
                f"返回类型={type(compare_result).__name__}"
            )
        cleaned = [item for item in compare_result if isinstance(item, dict)]
        await asyncio.to_thread(
            _save_cache_json, cache_dir, "pair", job["cache_key"], cleaned
        )
        return (job["a_key"], job["b_key"]), cleaned

    semaphore = asyncio.Semaphore(pair_concurrency)

    async def _worker(
        job: Dict[str, Any],
    ) -> Tuple[Tuple[str, str], List[Dict[str, Any]]]:
        async with semaphore:
            return await _run_pair_job(job)

    results = await asyncio.gather(
        *[_worker(job) for job in pair_jobs], return_exceptions=True
    )
    pair_compare_results: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
    for result in results:
        if isinstance(result, Exception):
            raise result
        pair_key, payload = result
        pair_compare_results[pair_key] = payload
    return pair_compare_results


# 功能说明：构建尺寸审核结果列表
def _build_dimension_issues(
    project_id: str,
    audit_version: int,
    pairs: List[Dict[str, str]],
    pair_compare_results: Dict[Tuple[str, str], List[Dict[str, Any]]],
    json_by_sheet: Dict[str, Dict[str, Any]],
) -> List[AuditResult]:
    issues: List[AuditResult] = []

    for pair in pairs:
        pair_result = pair_compare_results.get((pair["a"], pair["b"]))
        if not pair_result:
            continue
        a = json_by_sheet[pair["a"]]
        b = json_by_sheet[pair["b"]]
        for item in pair_result:
            parsed = parse_dimension_pair_item(item)
            value_a = parsed["value_a"]
            value_b = parsed["value_b"]
            desc = str(parsed["description"] or "").strip()
            source_grid = str(parsed["source_grid"] or "")
            target_grid = str(parsed["target_grid"] or "")
            source_dim_id = str(parsed["source_dim_id"] or "")
            target_dim_id = str(parsed["target_dim_id"] or "")
            index_hint = str(parsed["index_hint"] or "")
            confidence = float(parsed["confidence"] or 0.0)
            loc = str(parsed["location"] or "").strip()

            if desc:
                final_desc = desc
            else:
                try:
                    diff = abs(float(value_a or 0) - float(value_b or 0))
                    final_desc = (
                        f"{a['sheet_no']}标注为{value_a}mm，"
                        f"{b['sheet_no']}标注为{value_b}mm，"
                        f"差值{diff:.0f}mm"
                    )
                except (ValueError, TypeError):
                    final_desc = (
                        f"{a['sheet_no']}与{b['sheet_no']}的尺寸可能不一致，请核实"
                    )
            if index_hint:
                final_desc = f"{final_desc}（位置：{index_hint}）"

            raw_sheet_no_a = str(parsed["raw_sheet_no_a"] or "").strip()
            raw_sheet_no_b = str(parsed["raw_sheet_no_b"] or "").strip()
            sheet_no_a = (
                raw_sheet_no_a
                if normalize_sheet_no(raw_sheet_no_a) in json_by_sheet
                else a["sheet_no"]
            )
            sheet_no_b = (
                raw_sheet_no_b
                if normalize_sheet_no(raw_sheet_no_b) in json_by_sheet
                else b["sheet_no"]
            )

            issue = AuditResult(
                project_id=project_id,
                audit_version=audit_version,
                type="dimension",
                severity="warning",
                sheet_no_a=sheet_no_a,
                sheet_no_b=sheet_no_b,
                location=loc or None,
                value_a=str(value_a) if value_a is not None else None,
                value_b=str(value_b) if value_b is not None else None,
                description=final_desc,
                evidence_json=None,
            )

            anchors: List[Dict[str, Any]] = []
            source_dim_key = normalize_index_no(source_dim_id)
            target_dim_key = normalize_index_no(target_dim_id)
            source_dim = (
                a.get("dimension_lookup", {}).get(source_dim_key)
                if source_dim_key
                else None
            )
            target_dim = (
                b.get("dimension_lookup", {}).get(target_dim_key)
                if target_dim_key
                else None
            )

            source_anchor = build_anchor(
                role="source",
                sheet_no=issue.sheet_no_a or a["sheet_no"],
                grid=source_grid or (source_dim or {}).get("grid"),
                global_pct=(
                    (source_dim or {}).get("global_pct")
                    if isinstance((source_dim or {}).get("global_pct"), dict)
                    else None
                ),
                confidence=confidence,
                origin="dimension",
            )
            if source_anchor:
                anchors.append(source_anchor)

            target_anchor = build_anchor(
                role="target",
                sheet_no=issue.sheet_no_b or b["sheet_no"],
                grid=target_grid or (target_dim or {}).get("grid"),
                global_pct=(
                    (target_dim or {}).get("global_pct")
                    if isinstance((target_dim or {}).get("global_pct"), dict)
                    else None
                ),
                confidence=confidence,
                origin="dimension",
            )
            if target_anchor:
                anchors.append(target_anchor)

            issue.evidence_json = to_evidence_json(
                anchors,
                pair_id=f"{pair['a']}::{pair['b']}",
                unlocated_reason=None if anchors else "dimension_pair_unlocated",
            )
            issues.append(issue)

    return issues


# 功能说明：执行尺寸审核主函数，分析图纸间尺寸一致性
def audit_dimensions(
    project_id: str,
    audit_version: int,
    db,
    pair_filters: Optional[List[Tuple[str, str]]] = None,
) -> List[AuditResult]:
    from services.kimi_service import call_kimi

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError("项目不存在")

    cache_dir = _cache_dir_for_project(project)
    sheet_concurrency = _read_int_env("SHEET_AGENT_CONCURRENCY", 8, low=1, high=32)
    pair_concurrency = _read_int_env("PAIR_AGENT_CONCURRENCY", 16, low=1, high=64)
    prompt_version = os.getenv("DIMENSION_PROMPT_VERSION", "dim_v2_5img_v1")
    logger.info(
        "dimension_audit start project=%s version=%s sheet_concurrency=%s pair_concurrency=%s",
        project_id,
        audit_version,
        sheet_concurrency,
        pair_concurrency,
    )

    json_by_sheet = _load_json_by_sheet(project_id, db)
    page_assets_by_sheet = _load_drawing_assets(project_id, db)
    pairs = _build_pairs(json_by_sheet, pair_filters)
    if not pairs:
        if pair_filters is not None:
            return []
        raise RuntimeError("未发现可用于尺寸核对的索引图对，无法执行尺寸审核。")

    (
        semantic_cache,
        semantic_hashes,
        sheet_jobs,
        sheet_cache_hit,
        sheet_cache_miss,
        involved_total,
    ) = _prepare_sheet_semantic_inputs(
        json_by_sheet,
        page_assets_by_sheet,
        pairs,
        prompt_version,
        cache_dir,
        audit_version,
    )
    sheet_results = asyncio.run(
        _execute_sheet_jobs(sheet_jobs, sheet_concurrency, cache_dir, call_kimi)
    )
    for sheet_key, cleaned, cache_key in sheet_results:
        semantic_cache[sheet_key] = cleaned
        semantic_hashes[sheet_key] = _sha256_parts(
            [cache_key, _canonical_json(cleaned)]
        )
    logger.info(
        "dimension_audit sheet_semantic project=%s cache_hit=%s cache_miss=%s involved=%s",
        project_id,
        sheet_cache_hit,
        sheet_cache_miss,
        involved_total,
    )

    (
        pair_compare_results,
        pair_jobs,
        pair_cache_hit,
        pair_cache_miss,
    ) = _prepare_pair_compare_inputs(
        pairs,
        json_by_sheet,
        semantic_cache,
        semantic_hashes,
        prompt_version,
        cache_dir,
        audit_version,
    )
    pair_compare_results.update(
        asyncio.run(
            _execute_pair_jobs(pair_jobs, pair_concurrency, cache_dir, call_kimi)
        )
    )
    logger.info(
        "dimension_audit pair_compare project=%s cache_hit=%s cache_miss=%s pair_total=%s",
        project_id,
        pair_cache_hit,
        pair_cache_miss,
        len(pair_compare_results),
    )

    issues = _build_dimension_issues(
        project_id=project_id,
        audit_version=audit_version,
        pairs=pairs,
        pair_compare_results=pair_compare_results,
        json_by_sheet=json_by_sheet,
    )
    add_and_commit(db, issues)
    logger.info(
        "dimension_audit done project=%s version=%s issues=%s",
        project_id,
        audit_version,
        len(issues),
    )
    return issues
