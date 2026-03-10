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
from models import AuditResult, Drawing, JsonData, Project, SheetEdge
from services.ai_prompt_service import resolve_stage_system_prompt_with_skills
from services.audit.common import build_anchor, to_evidence_json
from services.audit.persistence import add_and_commit
from services.audit.prompt_builder import (
    build_pair_compare_prompt,
    build_single_sheet_prompt,
    build_visual_only_sheet_prompt,
    compact_dimensions,
)
from services.audit.result_parser import parse_dimension_pair_item
from services.audit_runtime.contracts import EvidencePack, EvidencePackType, EvidenceRequest
from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.evidence_planner import plan_evidence_requests
from services.audit_runtime.evidence_service import get_evidence_service
from services.audit_runtime.finding_schema import Finding, apply_finding_to_audit_result
from services.audit_runtime.hot_sheet_registry import HotSheetRegistry
from services.audit_runtime.providers.factory import build_runner_provider
from services.audit_runtime.runner_types import RunnerTurnRequest, RunnerTurnResult
from services.audit_runtime.cancel_registry import is_cancel_requested
from services.audit_runtime.state_transitions import append_run_event
from services.coordinate_service import cad_to_global_pct, enrich_json_with_coordinates
from services.feedback_runtime_service import load_feedback_runtime_profile
from services.kimi_service import call_kimi_stream
from services.skill_pack_service import load_runtime_skill_profile
from services.storage_path_service import resolve_project_dir

logger = logging.getLogger(__name__)


def _load_requested_provider_mode(project_id: str, audit_version: int) -> Optional[str]:
    from database import SessionLocal
    from models import AuditRun

    db = SessionLocal()
    try:
        run = (
            db.query(AuditRun)
            .filter(
                AuditRun.project_id == project_id,
                AuditRun.audit_version == audit_version,
            )
            .order_by(AuditRun.created_at.desc())
            .first()
        )
        value = str(getattr(run, "provider_mode", "") or "").strip()
        return value or None
    finally:
        db.close()


def _get_dimension_runner(
    project_id: str,
    audit_version: int,
    *,
    call_kimi,  # noqa: ANN001
) -> ProjectAuditAgentRunner:
    provider_mode = _load_requested_provider_mode(project_id, audit_version)
    shared_context = {"project_id": project_id, "audit_version": audit_version}
    if provider_mode:
        shared_context["provider_mode"] = provider_mode
    return ProjectAuditAgentRunner.get_or_create(
        project_id,
        audit_version=audit_version,
        provider=build_runner_provider(
            requested_mode=provider_mode,
            run_once_func=call_kimi,
            run_stream_func=call_kimi_stream,
        ),
        shared_context=shared_context,
    )


def _dimension_status_from_confidence(confidence: float, *, review_round: int = 1) -> str:
    if review_round >= 3:
        return "needs_review"
    if confidence >= 0.75:
        return "confirmed"
    return "suspected"


def _apply_dimension_finding(
    issue: AuditResult,
    *,
    confidence: float,
    review_round: int = 1,
    triggered_by: str | None = None,
) -> AuditResult:
    finding = Finding(
        sheet_no=str(issue.sheet_no_a or issue.sheet_no_b or "UNKNOWN").strip() or "UNKNOWN",
        location=str(issue.location or "未定位").strip() or "未定位",
        rule_id="dimension_pair_compare",
        finding_type="dim_mismatch",
        severity=str(issue.severity or "warning").strip().lower() or "warning",
        status=_dimension_status_from_confidence(confidence, review_round=review_round),  # type: ignore[arg-type]
        confidence=max(0.0, min(1.0, confidence)),
        source_agent="dimension_review_agent",
        evidence_pack_id="paired_overview_pack",
        review_round=review_round,
        triggered_by=triggered_by,
        description=str(issue.description or "").strip(),
    )
    return apply_finding_to_audit_result(issue, finding)


def _dimension_v2_enabled() -> bool:
    return str(os.getenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _dimension_stream_enabled() -> bool:
    raw = os.getenv("AUDIT_KIMI_STREAM_ENABLED")
    if raw is None:
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _append_dimension_stream_event(
    project_id: str,
    audit_version: int,
    *,
    event_kind: str,
    message: str,
    progress_hint: int,
    level: str = "info",
    meta: Dict[str, Any] | None = None,
) -> None:
    append_run_event(
        project_id,
        audit_version,
        level=level,
        step_key="dimension",
        agent_key="dimension_review_agent",
        agent_name="尺寸审查Agent",
        event_kind=event_kind,
        progress_hint=progress_hint,
        message=message,
        meta=meta or {},
    )


def resolve_dimension_runtime_policy(
    *,
    skill_profile: Dict[str, Any] | None = None,
    feedback_profile: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    floor = 0.0
    needs_secondary_review = bool((feedback_profile or {}).get("needs_secondary_review"))
    severity_override = (feedback_profile or {}).get("severity_override")
    hint = (feedback_profile or {}).get("experience_hint")

    skill_policy = ((skill_profile or {}).get("judgement_policy") or {}).get("dimension")
    if isinstance(skill_policy, dict):
        raw_floor = skill_policy.get("confidence_floor")
        if isinstance(raw_floor, (int, float)):
            floor = max(floor, float(raw_floor))
        if skill_policy.get("needs_secondary_review") is True:
            needs_secondary_review = True
        if skill_policy.get("severity_override"):
            severity_override = skill_policy.get("severity_override")

    if isinstance(hint, dict):
        raw_floor = hint.get("confidence_floor")
        if isinstance(raw_floor, (int, float)):
            floor = max(floor, float(raw_floor))
        if str(hint.get("intervention_level") or "").strip().lower() in {"soft", "hard"}:
            needs_secondary_review = True

    raw_feedback_floor = (feedback_profile or {}).get("confidence_floor")
    if isinstance(raw_feedback_floor, (int, float)):
        floor = max(floor, float(raw_feedback_floor))

    return {
        "confidence_floor": floor,
        "needs_secondary_review": needs_secondary_review,
        "severity_override": severity_override,
    }


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
    *,
    ai_edges: Optional[List[Tuple[str, str]]] = None,
) -> List[Dict[str, str]]:
    """构建需要对比的图纸对，合并三个来源：
    1. pair_filters（task planner 指定的）
    2. JSON indexes（DXF 提取的跨图引用）
    3. AI edges（AI 视觉发现的跨图关系）
    """
    pair_keys: set[Tuple[str, str]] = set()
    pairs: List[Dict[str, str]] = []

    def _add_pair(a_key: str, b_key: str) -> None:
        if a_key not in json_by_sheet or b_key not in json_by_sheet:
            return
        pk = tuple(sorted([a_key, b_key]))
        if pk in pair_keys:
            return
        pair_keys.add(pk)
        pairs.append({"a": pk[0], "b": pk[1]})

    # Source 1: task planner explicit pairs
    if pair_filters is not None:
        for a_raw, b_raw in pair_filters:
            a_key = normalize_sheet_no(a_raw)
            b_key = normalize_sheet_no(b_raw)
            if a_key and b_key and a_key != b_key:
                _add_pair(a_key, b_key)

    # Source 2: JSON indexes (DXF extracted cross-sheet references)
    for src_key, src in json_by_sheet.items():
        for idx in src["indexes"]:
            target_raw = str(idx.get("target_sheet", "") or "").strip()
            tgt_key = normalize_sheet_no(target_raw)
            if tgt_key and tgt_key != src_key:
                _add_pair(src_key, tgt_key)

    # Source 3: AI visual discovery edges
    if ai_edges:
        for a_raw, b_raw in ai_edges:
            a_key = normalize_sheet_no(a_raw)
            b_key = normalize_sheet_no(b_raw)
            if a_key and b_key and a_key != b_key:
                _add_pair(a_key, b_key)

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
        is_visual_only = not dims

        if dims:
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
        else:
            sheet["dimension_lookup"] = {}

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

        dims_compact = compact_dimensions(dims) if dims else []
        if is_visual_only:
            prompt = build_visual_only_sheet_prompt(
                sheet_no=sheet["sheet_no"],
                sheet_name=sheet["sheet_name"],
            )
        else:
            prompt = build_single_sheet_prompt(
                sheet_no=sheet["sheet_no"],
                sheet_name=sheet["sheet_name"],
                dims_compact=dims_compact,
            )
        sheet_cache_key = _sha256_parts(
            [
                prompt_version,
                "sheet_semantic_v2" if is_visual_only else "sheet_semantic",
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
                "visual_only": is_visual_only,
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
    *,
    project_id: str | None = None,
    audit_version: int | None = None,
) -> List[Tuple[str, List[Dict[str, Any]], str]]:
    if not sheet_jobs:
        return []
    evidence_service = get_evidence_service()
    v2_enabled = _dimension_v2_enabled()
    skill_profile = {"judgement_policy": {}, "evidence_bias": {}, "task_bias": {}}
    feedback_profile = {"needs_secondary_review": False}

    async def _run_sheet_job(
        job: Dict[str, Any],
    ) -> Tuple[str, List[Dict[str, Any]], str]:
        pack_type = EvidencePackType.DEEP_PACK
        if v2_enabled and not job.get("visual_only"):
            plans = plan_evidence_requests(
                task_type="dimension",
                source_sheet_no=job["sheet_no"],
                requires_visual=True,
                skill_profile=skill_profile,
                feedback_profile=feedback_profile,
                priority="normal",
            )
            if plans:
                pack_type = plans[0].pack_type
        pack = await evidence_service.get_evidence_pack(
            EvidenceRequest(
                pack_type=pack_type,
                source_pdf_path=job["pdf_path"],
                source_page_index=job["page_index"],
            )
        )
        stage_key = "dimension_visual_only" if job.get("visual_only") else "dimension_single_sheet"
        if pack_type == EvidencePackType.DEEP_PACK:
            images = [
                pack.images["source_full"],
                pack.images["source_top_left"],
                pack.images["source_top_right"],
                pack.images["source_bottom_left"],
                pack.images["source_bottom_right"],
            ]
        else:
            images = list(pack.images.values())
        if project_id is not None and audit_version is not None and _dimension_stream_enabled():
            runner = _get_dimension_runner(
                project_id,
                audit_version,
                call_kimi=call_kimi,
            )
            turn_result: RunnerTurnResult = await runner.run_stream(
                RunnerTurnRequest(
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    step_key="dimension",
                    progress_hint=29,
                    turn_kind="dimension_sheet_semantic",
                    system_prompt=resolve_stage_system_prompt_with_skills(
                        stage_key,
                        "dimension",
                    ),
                    user_prompt=job["prompt"],
                    images=images,
                    temperature=0.0,
                    meta={
                        "mode": "sheet_semantic",
                        "sheet_no": job["sheet_no"],
                        "visual_only": bool(job.get("visual_only")),
                        "pack_type": pack_type.value,
                    },
                ),
                should_cancel=lambda: is_cancel_requested(project_id),
            )
            semantic_result = turn_result.output if turn_result.status != "needs_review" else []
        else:
            runner = _get_dimension_runner(
                project_id or "__adhoc_dimension__",
                audit_version or 0,
                call_kimi=call_kimi,
            )
            turn_result: RunnerTurnResult = await runner.run_once(
                RunnerTurnRequest(
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    step_key="dimension",
                    progress_hint=29,
                    turn_kind="dimension_sheet_semantic",
                    system_prompt=resolve_stage_system_prompt_with_skills(
                        stage_key,
                        "dimension",
                    ),
                    user_prompt=job["prompt"],
                    images=images,
                    temperature=0.0,
                )
            )
            semantic_result = turn_result.output if turn_result.status != "needs_review" else []
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
    page_assets_by_sheet: Dict[str, Dict[str, Any]],
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
                "pair_compare_v2",
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

        # Collect PDF info for image rendering during pair comparison
        a_asset = page_assets_by_sheet.get(pair["a"], {})
        b_asset = page_assets_by_sheet.get(pair["b"], {})

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
                "a_pdf_path": str(a_asset.get("pdf_path", "")),
                "a_page_index": int(a_asset.get("page_index", 0)),
                "b_pdf_path": str(b_asset.get("pdf_path", "")),
                "b_page_index": int(b_asset.get("page_index", 0)),
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
    *,
    project_id: str | None = None,
    audit_version: int | None = None,
) -> Dict[Tuple[str, str], List[Dict[str, Any]]]:
    if not pair_jobs:
        return {}
    evidence_service = get_evidence_service()
    v2_enabled = _dimension_v2_enabled()
    skill_profile = {"judgement_policy": {}, "evidence_bias": {}, "task_bias": {}}
    feedback_profile = {"needs_secondary_review": False}

    async def _run_pair_job(
        job: Dict[str, Any],
    ) -> Tuple[Tuple[str, str], List[Dict[str, Any]]]:
        pair_images: List[bytes] = []
        if job.get("a_pdf_path") and job.get("b_pdf_path"):
            try:
                pack_type = EvidencePackType.PAIRED_OVERVIEW_PACK
                if v2_enabled:
                    plans = plan_evidence_requests(
                        task_type="dimension",
                        source_sheet_no=job["a_sheet_no"],
                        target_sheet_no=job["b_sheet_no"],
                        requires_visual=True,
                        skill_profile=skill_profile,
                        feedback_profile=feedback_profile,
                        priority="high",
                    )
                    if plans:
                        if plans[0].pack_type == EvidencePackType.OVERVIEW_PACK:
                            pack_type = EvidencePackType.PAIRED_OVERVIEW_PACK
                        else:
                            pack_type = plans[0].pack_type
                pack = await evidence_service.get_evidence_pack(
                    EvidenceRequest(
                        pack_type=pack_type,
                        source_pdf_path=job["a_pdf_path"],
                        source_page_index=job["a_page_index"],
                        target_pdf_path=job["b_pdf_path"],
                        target_page_index=job["b_page_index"],
                    )
                )
                pair_images = list(pack.images.values())
            except Exception:
                pair_images = []

        if project_id is not None and audit_version is not None and _dimension_stream_enabled():
            runner = _get_dimension_runner(
                project_id,
                audit_version,
                call_kimi=call_kimi,
            )
            turn_result: RunnerTurnResult = await runner.run_stream(
                RunnerTurnRequest(
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    step_key="dimension",
                    progress_hint=31,
                    turn_kind="dimension_pair_compare",
                    system_prompt=resolve_stage_system_prompt_with_skills(
                        "dimension_pair_compare",
                        "dimension",
                    ),
                    user_prompt=build_pair_compare_prompt(
                        a_sheet_no=job["a_sheet_no"],
                        a_sheet_name=job["a_sheet_name"],
                        a_semantic=job["semantic_a"],
                        b_sheet_no=job["b_sheet_no"],
                        b_sheet_name=job["b_sheet_name"],
                        b_semantic=job["semantic_b"],
                    ),
                    images=pair_images if pair_images else [],
                    temperature=0.0,
                    meta={
                        "mode": "pair_compare",
                        "source_sheet_no": job["a_sheet_no"],
                        "target_sheet_no": job["b_sheet_no"],
                    },
                ),
                should_cancel=lambda: is_cancel_requested(project_id),
            )
            compare_result = turn_result.output if turn_result.status != "needs_review" else []
        else:
            runner = _get_dimension_runner(
                project_id or "__adhoc_dimension__",
                audit_version or 0,
                call_kimi=call_kimi,
            )
            turn_result: RunnerTurnResult = await runner.run_once(
                RunnerTurnRequest(
                    agent_key="dimension_review_agent",
                    agent_name="尺寸审查Agent",
                    step_key="dimension",
                    progress_hint=31,
                    turn_kind="dimension_pair_compare",
                    system_prompt=resolve_stage_system_prompt_with_skills(
                        "dimension_pair_compare",
                        "dimension",
                    ),
                    user_prompt=build_pair_compare_prompt(
                        a_sheet_no=job["a_sheet_no"],
                        a_sheet_name=job["a_sheet_name"],
                        a_semantic=job["semantic_a"],
                        b_sheet_no=job["b_sheet_no"],
                        b_sheet_name=job["b_sheet_name"],
                        b_semantic=job["semantic_b"],
                    ),
                    images=pair_images if pair_images else [],
                    temperature=0.0,
                )
            )
            compare_result = turn_result.output if turn_result.status != "needs_review" else []
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
    runtime_policy: Dict[str, Any] | None = None,
) -> List[AuditResult]:
    issues: List[AuditResult] = []
    confidence_floor = float((runtime_policy or {}).get("confidence_floor") or 0.0)
    severity_override = str((runtime_policy or {}).get("severity_override") or "").strip().lower() or None

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
            source_pct = parsed.get("source_pct")
            target_pct = parsed.get("target_pct")
            source_grid = str(parsed["source_grid"] or "")
            target_grid = str(parsed["target_grid"] or "")
            source_dim_id = str(parsed["source_dim_id"] or "")
            target_dim_id = str(parsed["target_dim_id"] or "")
            index_hint = str(parsed["index_hint"] or "")
            confidence = float(parsed["confidence"] or 0.0)
            if confidence_floor and confidence < confidence_floor:
                continue
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
                severity=severity_override or "warning",
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

            # Prefer AI-output pct, fallback to JSON dimension's global_pct
            resolved_source_pct = source_pct or (
                (source_dim or {}).get("global_pct")
                if isinstance((source_dim or {}).get("global_pct"), dict)
                else None
            )
            resolved_target_pct = target_pct or (
                (target_dim or {}).get("global_pct")
                if isinstance((target_dim or {}).get("global_pct"), dict)
                else None
            )

            source_anchor = build_anchor(
                role="source",
                sheet_no=issue.sheet_no_a or a["sheet_no"],
                grid=source_grid or (source_dim or {}).get("grid"),
                global_pct=resolved_source_pct,
                confidence=confidence,
                origin="dimension",
            )
            if source_anchor:
                anchors.append(source_anchor)

            target_anchor = build_anchor(
                role="target",
                sheet_no=issue.sheet_no_b or b["sheet_no"],
                grid=target_grid or (target_dim or {}).get("grid"),
                global_pct=resolved_target_pct,
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
            _apply_dimension_finding(
                issue,
                confidence=confidence,
                review_round=1,
            )
            issues.append(issue)

    return issues


# 功能说明：执行尺寸审核主函数，分析图纸间尺寸一致性
def audit_dimensions(
    project_id: str,
    audit_version: int,
    db,
    pair_filters: Optional[List[Tuple[str, str]]] = None,
    hot_sheet_registry: HotSheetRegistry | None = None,
) -> List[AuditResult]:
    from services.kimi_service import call_kimi

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise ValueError("项目不存在")
    skill_profile = load_runtime_skill_profile(
        db,
        skill_type="dimension",
        stage_key="dimension_pair_compare",
    )
    feedback_profile = load_feedback_runtime_profile(db, issue_type="dimension")
    runtime_policy = resolve_dimension_runtime_policy(
        skill_profile=skill_profile,
        feedback_profile=feedback_profile,
    )

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

    # Load AI-discovered edges as additional pair source
    ai_edges: List[Tuple[str, str]] = []
    try:
        ai_edge_rows = (
            db.query(SheetEdge)
            .filter(
                SheetEdge.project_id == project_id,
                SheetEdge.edge_type == "ai_visual",
            )
            .all()
        )
        ai_edges = [
            (e.source_sheet_no, e.target_sheet_no)
            for e in ai_edge_rows
            if e.source_sheet_no and e.target_sheet_no
        ]
    except Exception as exc:
        logger.warning("加载AI关系边失败: %s", exc)

    pairs = _build_pairs(json_by_sheet, pair_filters, ai_edges=ai_edges)
    if hot_sheet_registry is not None:
        pairs = sorted(
            pairs,
            key=lambda pair: (
                -max(
                    hot_sheet_registry.score(json_by_sheet.get(pair["a"], {}).get("sheet_no")),
                    hot_sheet_registry.score(json_by_sheet.get(pair["b"], {}).get("sheet_no")),
                ),
                pair["a"],
                pair["b"],
            ),
        )
    logger.info(
        "dimension_audit pairs=%s (filters=%s, ai_edges=%s)",
        len(pairs), len(pair_filters) if pair_filters else "none", len(ai_edges),
    )
    if not pairs:
        if pair_filters is not None:
            return []
        logger.warning("未发现可用于尺寸核对的索引图对，跳过尺寸审核。")
        return []

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

    async def _run_all_async() -> Tuple[
        Dict[Tuple[str, str], List[Dict[str, Any]]], int, int
    ]:
        sheet_results = await _execute_sheet_jobs(
            sheet_jobs,
            sheet_concurrency,
            cache_dir,
            call_kimi,
            project_id=project_id,
            audit_version=audit_version,
        )
        for s_key, cleaned, c_key in sheet_results:
            semantic_cache[s_key] = cleaned
            semantic_hashes[s_key] = _sha256_parts(
                [c_key, _canonical_json(cleaned)]
            )
        logger.info(
            "dimension_audit sheet_semantic project=%s cache_hit=%s cache_miss=%s involved=%s",
            project_id, sheet_cache_hit, sheet_cache_miss, involved_total,
        )

        pc_results, p_jobs, pc_hit, pc_miss = _prepare_pair_compare_inputs(
            pairs, json_by_sheet, page_assets_by_sheet, semantic_cache, semantic_hashes,
            prompt_version, cache_dir, audit_version,
        )
        pc_results.update(
            await _execute_pair_jobs(
                p_jobs,
                pair_concurrency,
                cache_dir,
                call_kimi,
                project_id=project_id,
                audit_version=audit_version,
            )
        )
        return pc_results, pc_hit, pc_miss

    pair_compare_results, pair_cache_hit, pair_cache_miss = asyncio.run(
        _run_all_async()
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
        runtime_policy=runtime_policy,
    )
    if hot_sheet_registry is not None:
        for issue in issues:
            confidence = float(getattr(issue, "confidence", None) or 0.72)
            hot_sheet_registry.publish(
                issue.sheet_no_a,
                finding_type=getattr(issue, "finding_type", None) or "dim_mismatch",
                confidence=confidence,
                source_agent="dimension_review_agent",
            )
            hot_sheet_registry.publish(
                issue.sheet_no_b,
                finding_type=getattr(issue, "finding_type", None) or "dim_mismatch",
                confidence=confidence,
                source_agent="dimension_review_agent",
            )
    add_and_commit(db, issues)
    logger.info(
        "dimension_audit done project=%s version=%s issues=%s",
        project_id,
        audit_version,
        len(issues),
    )
    return issues
