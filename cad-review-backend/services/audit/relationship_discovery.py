"""AI 驱动的图纸关系发现服务。

通过 AI 视觉理解图纸内容，自动发现跨图引用关系（索引、详图引用等），
不再完全依赖 DXF JSON 提取的 indexes[].target_sheet 数据。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import time
from typing import Any, Dict, List, Tuple

from domain.sheet_normalization import normalize_sheet_no
from models import Catalog, Drawing, JsonData, SheetEdge
from services.audit.image_pipeline import pdf_page_to_5images
from services.coordinate_service import enrich_json_with_coordinates
from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.agent_reports import RelationshipAgentReport
from services.audit_runtime.contracts import EvidencePack, EvidencePackType, EvidencePlanItem, EvidenceRequest
from services.audit_runtime.evidence_planner import plan_deep, plan_evidence_requests, plan_lite
from services.audit_runtime.evidence_service import EvidenceService
from services.audit_runtime.finding_schema import Finding
from services.audit_runtime.runtime_prompt_assembler import (
    RuntimePromptBundle,
    assemble_legacy_stage_prompt,
    render_legacy_stage_user_prompt,
)
from services.audit_runtime.hot_sheet_registry import HotSheetRegistry
from services.audit_runtime.providers.factory import build_runner_provider, normalize_provider_mode
from services.audit_runtime.review_task_schema import WorkerResultCard, WorkerTaskCard
from services.audit_runtime.runner_types import RunnerTurnRequest, RunnerTurnResult
from services.audit_runtime.cancel_registry import AuditCancellationRequested, is_cancel_requested
from services.audit_runtime.state_transitions import append_agent_status_report, append_run_event
from services.audit_runtime.stream_policy import audit_stream_enabled
from services.feedback_runtime_service import load_feedback_runtime_profile
from services.ai_service import call_kimi_stream
from services.skill_pack_service import load_runtime_skill_profile

logger = logging.getLogger(__name__)

_DEFAULT_GROUP_SIZE = 4


def _relationship_subsession_key(scope: str, *sheet_nos: str) -> str:
    normalized = [
        normalize_sheet_no(sheet_no) or str(sheet_no or "").strip()
        for sheet_no in sheet_nos
        if str(sheet_no or "").strip()
    ]
    digest = hashlib.sha1("|".join(normalized).encode("utf-8")).hexdigest()[:12]
    return f"{scope}:{digest}"


def _build_relationship_agent_report(
    turn_result: RunnerTurnResult,
    *,
    stage: str,
    source_sheet_no: str = "",
    target_sheet_no: str = "",
    cleaned: List[Dict[str, Any]] | None = None,
) -> RelationshipAgentReport:
    event_kinds = {
        str(item.event_kind or "").strip()
        for item in (turn_result.events or [])
        if str(item.event_kind or "").strip()
    }
    blocking_issues: List[Dict[str, Any]] = []
    unstable = (
        turn_result.status != "ok"
        or turn_result.repair_attempts > 0
        or "output_validation_failed" in event_kinds
    )
    if unstable:
        blocking_issues.append(
            {
                "kind": "unstable_output",
                "stage": stage,
                "source_sheet_no": str(source_sheet_no or "").strip(),
                "target_sheet_no": str(target_sheet_no or "").strip(),
                "reason": turn_result.error or "runner_output_unstable",
            }
        )

    scope = "关系候选复核" if stage == "candidate_review" else "关系分组整理"
    pair_label = " / ".join(
        item for item in [str(source_sheet_no or "").strip(), str(target_sheet_no or "").strip()] if item
    )
    summary = f"关系审查Agent 已完成一批{scope}"
    if pair_label:
        summary = f"{summary}（{pair_label}）"

    if blocking_issues:
        help_request = "restart_subsession"
        next_action = "rerun_current_batch"
        confidence = 0.35
    else:
        help_request = ""
        next_action = "continue"
        confidence = 0.86 if list(cleaned or []) else 0.6

    return RelationshipAgentReport(
        batch_summary=summary,
        confirmed_findings=[],
        suspected_findings=[],
        blocking_issues=blocking_issues,
        runner_help_request=help_request,
        agent_confidence=confidence,
        next_recommended_action=next_action,
    )


def get_evidence_service():
    return EvidenceService(renderer=pdf_page_to_5images)


def _get_relationship_runner(
    project_id: str,
    audit_version: int,
    *,
    call_kimi,  # noqa: ANN001
) -> ProjectAuditAgentRunner:
    provider_mode = _load_requested_provider_mode(project_id, audit_version)
    runner_signature = (
        f"{provider_mode or 'env'}:{id(call_kimi)}:{id(call_kimi_stream)}"
    )
    existing = ProjectAuditAgentRunner.get_existing(project_id, audit_version=audit_version)
    if existing and str(existing.shared_context.get("runner_signature") or "") != runner_signature:
        ProjectAuditAgentRunner.drop(project_id, audit_version=audit_version)
    shared_context = {
        "project_id": project_id,
        "audit_version": audit_version,
        "runner_signature": runner_signature,
    }
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


def _load_requested_provider_mode(project_id: str, audit_version: int) -> str | None:
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
        raw_mode = str(getattr(run, "provider_mode", "") or "").strip() if run else ""
        if not raw_mode:
            return None
        return normalize_provider_mode(raw_mode) or None
    finally:
        db.close()


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return value if value > 0 else default


def _relationship_render_options() -> Dict[str, float | int]:
    return {
        "full_dpi": _env_float("AUDIT_RELATIONSHIP_DISCOVERY_FULL_DPI", 144.0),
        "detail_dpi": _env_float("AUDIT_RELATIONSHIP_DISCOVERY_DETAIL_DPI", 216.0),
        "max_width": _env_int("AUDIT_RELATIONSHIP_DISCOVERY_MAX_WIDTH", 2800),
    }


def _relationship_stream_enabled() -> bool:
    return audit_stream_enabled(default=False)


def _append_relationship_stream_event(
    project_id: str,
    audit_version: int,
    *,
    level: str,
    event_kind: str,
    message: str,
    progress_hint: int,
    meta: Dict[str, Any] | None = None,
) -> None:
    append_run_event(
        project_id,
        audit_version,
        level=level,
        step_key="relationship_discovery",
        agent_key="relationship_review_agent",
        agent_name="关系审查Agent",
        event_kind=event_kind,
        progress_hint=progress_hint,
        message=message,
        meta=meta or {},
    )


def _relationship_confidence_floor(
    *,
    skill_profile: Dict[str, Any] | None,
    feedback_profile: Dict[str, Any] | None,
) -> float:
    floor = 0.0
    skill_policy = ((skill_profile or {}).get("judgement_policy") or {}).get("relationship")
    if isinstance(skill_policy, dict):
        raw = skill_policy.get("confidence_floor")
        if isinstance(raw, (int, float)):
            floor = max(floor, float(raw))
    hint = feedback_profile.get("experience_hint") if isinstance(feedback_profile, dict) else None
    if isinstance(hint, dict):
        raw = hint.get("confidence_floor")
        if isinstance(raw, (int, float)):
            floor = max(floor, float(raw))
    feedback_floor = feedback_profile.get("confidence_floor") if isinstance(feedback_profile, dict) else None
    if isinstance(feedback_floor, (int, float)):
        floor = max(floor, float(feedback_floor))
    return floor


def apply_relationship_runtime_policy(
    raw_relationships: List[Dict[str, Any]],
    *,
    skill_profile: Dict[str, Any] | None = None,
    feedback_profile: Dict[str, Any] | None = None,
) -> List[Dict[str, Any]]:
    confidence_floor = _relationship_confidence_floor(
        skill_profile=skill_profile,
        feedback_profile=feedback_profile,
    )
    if confidence_floor <= 0:
        return list(raw_relationships)

    filtered: List[Dict[str, Any]] = []
    for rel in raw_relationships:
        try:
            confidence = float(rel.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        if confidence >= confidence_floor:
            filtered.append(rel)
    return filtered


def _relationship_status_from_confidence(confidence: float, *, review_round: int) -> str:
    if review_round >= 3:
        return "needs_review"
    if confidence >= 0.75:
        return "confirmed"
    return "suspected"


def _relationship_needs_more_evidence(
    confidence: float,
    *,
    skill_profile: Dict[str, Any] | None,
    feedback_profile: Dict[str, Any] | None,
    review_round: int,
) -> bool:
    if review_round >= 2:
        return False
    floor = _relationship_confidence_floor(
        skill_profile=skill_profile,
        feedback_profile=feedback_profile,
    )
    threshold = floor if floor > 0 else 0.75
    return confidence < threshold


def _relationship_below_threshold(
    confidence: float,
    *,
    skill_profile: Dict[str, Any] | None,
    feedback_profile: Dict[str, Any] | None,
) -> bool:
    floor = _relationship_confidence_floor(
        skill_profile=skill_profile,
        feedback_profile=feedback_profile,
    )
    threshold = floor if floor > 0 else 0.75
    return confidence < threshold


def _should_skip_relationship_candidate_review(
    source_sheet: Dict[str, Any],
    target_sheet: Dict[str, Any],
) -> str | None:
    source_sheet_no = str(source_sheet.get("sheet_no") or "").strip()
    target_sheet_no = str(target_sheet.get("sheet_no") or "").strip()
    if not source_sheet_no or not target_sheet_no:
        return "missing_sheet_no"
    if normalize_sheet_no(source_sheet_no) == normalize_sheet_no(target_sheet_no):
        return "self_pair"
    if not source_sheet.get("pdf_path") or source_sheet.get("page_index") is None:
        return "missing_source_asset"
    if not target_sheet.get("pdf_path") or target_sheet.get("page_index") is None:
        return "missing_target_asset"
    return None


def relationship_to_finding(
    relationship: Dict[str, Any],
    *,
    review_round: int = 1,
    triggered_by: str | None = None,
) -> Finding:
    source_sheet = str(relationship.get("source") or relationship.get("source_key") or "").strip() or "UNKNOWN"
    target_sheet = str(relationship.get("target") or relationship.get("target_key") or "").strip()
    relation = str(relationship.get("relation") or "ai_visual").strip() or "ai_visual"
    visual_evidence = str(relationship.get("visual_evidence") or "").strip()
    try:
        confidence = float(relationship.get("confidence") or 0.5)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))
    location = f"{source_sheet} -> {target_sheet or '待确认目标图'}"
    description = (
        visual_evidence
        or f"关系审查Agent 发现 {source_sheet} 与 {target_sheet or '目标图'} 之间存在 {relation} 线索"
    )
    evidence_pack_id = str(relationship.get("evidence_pack_id") or "paired_overview_pack").strip() or "paired_overview_pack"
    return Finding(
        sheet_no=source_sheet,
        location=location,
        rule_id="relationship_visual_review",
        finding_type="missing_ref",
        severity="warning",
        status=_relationship_status_from_confidence(confidence, review_round=review_round),  # type: ignore[arg-type]
        confidence=confidence,
        source_agent="relationship_review_agent",
        evidence_pack_id=evidence_pack_id,
        review_round=review_round,
        triggered_by=triggered_by,
        description=description,
    )


def attach_relationship_findings(
    relationships: List[Dict[str, Any]],
    *,
    review_round: int = 1,
    triggered_by: str | None = None,
) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for relationship in relationships:
        item = dict(relationship)
        item["finding"] = relationship_to_finding(
            relationship,
            review_round=review_round,
            triggered_by=triggered_by,
        ).model_dump()
        enriched.append(item)
    return enriched


def _build_relationship_task_prompt(source_sheet: Dict[str, Any], target_sheet: Dict[str, Any]) -> str:
    return (
        f"请判断图纸 {source_sheet['sheet_no']} {source_sheet['sheet_name']} 与 "
        f"{target_sheet['sheet_no']} {target_sheet['sheet_name']} 是否存在跨图引用关系。\n"
        "你将收到两张图：第1张为源图全图，第2张为目标图全图。\n"
        "重点检查源图中是否明确指向目标图的索引、详图、剖面或放大标记。\n"
        "输出纪律：\n"
        "1. 不要输出分析过程，不要解释你是怎么判断的\n"
        "2. 不要输出 markdown，不要输出 ```json 代码块\n"
        "3. 只有明确看到跨图引用时才输出；证据不够就不要猜\n"
        "4. 没有跨图引用关系就只返回[]\n"
        "5. target 必须就是当前目标图号，不允许输出其他目标图\n"
        "只返回 JSON 数组，格式固定为：\n"
        '[{"source":"图号","target":"目标图号","relation":"index_ref|detail_ref|section_ref|elevation_ref|callout_ref","confidence":0.0,"visual_evidence":"你看到的具体符号或文字","global_pct":{"x":0,"y":0},"index_label":"索引编号或标记文字"}]'
    )


def _build_candidate_relationship_tasks(
    sheets: List[Dict[str, Any]],
    valid_sheet_nos: set[str],
) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    sheet_by_key = {
        normalize_sheet_no(sheet["sheet_no"]): sheet
        for sheet in sheets
        if normalize_sheet_no(sheet["sheet_no"])
    }
    tasks: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    seen: set[Tuple[str, str]] = set()

    for sheet in sheets:
        src_key = normalize_sheet_no(sheet["sheet_no"])
        if not src_key:
            continue
        for idx in sheet.get("indexes_json") or []:
            target_sheet = str(idx.get("target_sheet") or "").strip()
            tgt_key = normalize_sheet_no(target_sheet)
            if not tgt_key or tgt_key not in valid_sheet_nos:
                continue
            target = sheet_by_key.get(tgt_key)
            if not target:
                continue
            pair = (src_key, tgt_key)
            if pair in seen:
                continue
            seen.add(pair)
            tasks.append((sheet, target))
    return tasks


def _load_ready_sheets(
    project_id: str,
    db,
    *,
    sheet_filters: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Load all ready sheets with their catalog info, JSON data, and drawing assets."""
    allowed_sheet_nos = {
        normalize_sheet_no(item)
        for item in list(sheet_filters or [])
        if normalize_sheet_no(item)
    }
    catalog_items = (
        db.query(Catalog)
        .filter(Catalog.project_id == project_id, Catalog.status == "locked")
        .order_by(Catalog.sort_order.asc())
        .all()
    )

    sheets: List[Dict[str, Any]] = []
    for cat in catalog_items:
        json_data = (
            db.query(JsonData)
            .filter(
                JsonData.project_id == project_id,
                JsonData.catalog_id == cat.id,
                JsonData.is_latest == 1,
            )
            .first()
        )
        drawing = (
            db.query(Drawing)
            .filter(
                Drawing.project_id == project_id,
                Drawing.catalog_id == cat.id,
                Drawing.replaced_at == None,
            )
            .first()
        )
        if not json_data or not drawing:
            continue

        sheet_no = cat.sheet_no or json_data.sheet_no or ""
        if not sheet_no.strip():
            continue
        if allowed_sheet_nos and normalize_sheet_no(sheet_no) not in allowed_sheet_nos:
            continue

        # Load JSON payload for index data (as reference)
        indexes_data: List[Dict[str, Any]] = []
        if json_data.json_path:
            try:
                with open(json_data.json_path, "r", encoding="utf-8") as f:
                    payload = json.load(f)
                enriched = enrich_json_with_coordinates(payload)
                indexes_data = enriched.get("indexes", []) or []
            except Exception:
                pass

        # Find PDF path and page index for image rendering
        pdf_path = getattr(drawing, "pdf_path", None) or ""
        page_index = getattr(drawing, "page_index", None)
        if not pdf_path:
            # Try to find PDF in the PNG directory
            png_path = getattr(drawing, "png_path", None) or ""
            if png_path:
                from pathlib import Path
                folder = Path(png_path).expanduser().resolve().parent
                pdfs = sorted(folder.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True)
                if pdfs:
                    pdf_path = str(pdfs[0])
                    if page_index is None:
                        page_index = getattr(drawing, "page_index", 0) or 0

        sheets.append({
            "sheet_no": sheet_no.strip(),
            "sheet_name": (cat.sheet_name or "").strip(),
            "catalog_id": cat.id,
            "pdf_path": pdf_path,
            "page_index": page_index if page_index is not None else 0,
            "indexes_json": indexes_data,
        })

    return sheets


def _relationship_worker_result_from_relationships(
    task: WorkerTaskCard,
    relationships: List[Dict[str, Any]],
) -> WorkerResultCard:
    if not relationships:
        return WorkerResultCard(
            task_id=task.id,
            hypothesis_id=task.hypothesis_id,
            worker_kind=task.worker_kind,
            status="rejected",
            confidence=0.71,
            summary=f"旧关系发现入口已作为 worker 包装层执行，{task.source_sheet_no} 未发现跨图引用问题",
            meta={
                "compat_mode": "worker_wrapper",
                "execution_mode": "worker_wrapper",
                "legacy_fallback": True,
                "fallback_origin": "legacy_relationship_wrapper",
                "sheet_no": task.source_sheet_no,
                "location": task.objective,
                "rule_id": "relationship_visual_review",
                "evidence_pack_id": "paired_overview_pack",
                "issue_count": 0,
            },
        )

    evidence: List[Dict[str, Any]] = []
    confidence = 0.81
    for item in relationships[:5]:
        finding = dict(item.get("finding") or {})
        confidence = max(confidence, float(item.get("confidence") or finding.get("confidence") or 0.81))
        evidence.append(
            {
                "sheet_no": str(finding.get("sheet_no") or item.get("source") or task.source_sheet_no or "UNKNOWN").strip() or "UNKNOWN",
                "location": str(finding.get("location") or f"{item.get('source')} -> {item.get('target')}").strip() or "未定位",
                "rule_id": str(finding.get("rule_id") or "relationship_visual_review").strip() or "relationship_visual_review",
                "evidence_pack_id": str(finding.get("evidence_pack_id") or item.get("evidence_pack_id") or "paired_overview_pack").strip() or "paired_overview_pack",
                "description": str(finding.get("description") or item.get("visual_evidence") or "").strip(),
                "severity": str(finding.get("severity") or "warning").strip().lower() or "warning",
            }
        )
    first = evidence[0]
    return WorkerResultCard(
        task_id=task.id,
        hypothesis_id=task.hypothesis_id,
        worker_kind=task.worker_kind,
        status="confirmed",
        confidence=confidence,
        summary=first["description"] or f"旧关系发现入口返回 {len(relationships)} 处跨图关联问题",
        evidence=evidence,
        meta={
            "compat_mode": "worker_wrapper",
            "execution_mode": "worker_wrapper",
            "legacy_fallback": True,
            "fallback_origin": "legacy_relationship_wrapper",
            "sheet_no": first["sheet_no"],
            "location": first["location"],
            "rule_id": first["rule_id"],
            "evidence_pack_id": first["evidence_pack_id"],
            "severity": first["severity"],
            "issue_count": len(relationships),
            "review_round": 1,
        },
    )


def run_relationship_worker_wrapper(
    project_id: str,
    audit_version: int,
    db,
    task: WorkerTaskCard,
) -> WorkerResultCard:
    sheet_filters = [task.source_sheet_no, *list(task.target_sheet_nos or [])]
    relationships = discover_relationships_v2(
        project_id,
        db,
        audit_version=audit_version,
        sheet_filters=sheet_filters,
    )
    return _relationship_worker_result_from_relationships(task, relationships)


def _classify_sheet_type(sheet_no: str, sheet_name: str) -> str:
    """Classify sheet into a group for batched AI calls."""
    combined = f"{sheet_no} {sheet_name}".upper()
    if any(kw in combined for kw in ("平面", "PLAN", "PL-P", "FURNITURE", "LAYOUT", "FLOOR", "CEILING", "天花", "地坪", "布置")):
        return "plan"
    if any(kw in combined for kw in ("立面", "ELEV", "EL-", "EL.", "SECTION")):
        return "elevation"
    if any(kw in combined for kw in ("详图", "DETAIL", "FU.", "FU-", "CABINET", "BOOTH", "节点")):
        return "detail"
    if any(kw in combined for kw in ("材料", "MATERIAL", "说明", "NOTE", "GENERAL", "索引", "INDEX", "目录", "COVER")):
        return "reference"
    return "other"


def _group_sheets(sheets: List[Dict[str, Any]], group_size: int | None = None) -> List[List[Dict[str, Any]]]:
    """Group sheets by type, then split into batches of configured size."""
    resolved_group_size = group_size or _env_int(
        "AUDIT_RELATIONSHIP_DISCOVERY_GROUP_SIZE",
        _DEFAULT_GROUP_SIZE,
    )
    by_type: Dict[str, List[Dict[str, Any]]] = {}
    for sheet in sheets:
        stype = _classify_sheet_type(sheet["sheet_no"], sheet["sheet_name"])
        by_type.setdefault(stype, []).append(sheet)

    groups: List[List[Dict[str, Any]]] = []
    for stype in ["plan", "elevation", "detail", "reference", "other"]:
        type_sheets = by_type.get(stype, [])
        for i in range(0, len(type_sheets), resolved_group_size):
            groups.append(type_sheets[i : i + resolved_group_size])
    return groups


def _build_discovery_prompt(
    group_sheets: List[Dict[str, Any]],
    all_catalog_entries: List[Dict[str, str]],
) -> str:
    """Build the user prompt for relationship discovery."""
    catalog_text = json.dumps(all_catalog_entries, ensure_ascii=False)

    sheet_descriptions: List[str] = []
    for i, sheet in enumerate(group_sheets):
        idx_summary = ""
        if sheet["indexes_json"]:
            idx_refs = []
            for idx in sheet["indexes_json"][:20]:
                no = idx.get("index_no", "")
                target = idx.get("target_sheet", "")
                pct = idx.get("global_pct", {})
                pct_str = f"x:{pct.get('x',0):.0f}%,y:{pct.get('y',0):.0f}%" if pct else "?"
                if no or target:
                    idx_refs.append(f"索引{no}→{target or '?'}(位置:{pct_str})")
            if idx_refs:
                idx_summary = f"\n  JSON提取的索引参考（可能不完整）：{'; '.join(idx_refs)}"

        sheet_descriptions.append(
            f"图{i + 1}: {sheet['sheet_no']} {sheet['sheet_name']}{idx_summary}"
        )

    return (
        "请分析以下图纸，找出所有跨图引用关系。\n\n"
        f"项目完整目录（{len(all_catalog_entries)}张图）：\n{catalog_text}\n\n"
        f"本批图纸（{len(group_sheets)}张，每张对应5张图片：全图+4象限）：\n"
        + "\n".join(sheet_descriptions)
        + "\n\n"
        "图片排列顺序：按图纸顺序，每张图纸依次为[全图总览, 左上象限(高清+刻度), 右上象限, 左下象限, 右下象限]。\n"
        "象限图边缘标有百分比刻度（0%~100%），与全图坐标系一致，可直接读取位置。\n\n"
        "请仔细查看每张图纸中的：\n"
        "1. 索引符号（圆圈，上方编号、下方目标图号；下方为短横线表示本图索引）\n"
        "2. 详图标签（圆圈内编号+图号）\n"
        "3. 剖面/断面符号\n"
        "4. 放大区域标记\n\n"
        "输出要求：\n"
        "- 只输出跨图引用（source 和 target 不同的图）\n"
        "- 每个引用必须包含百分比坐标 global_pct（x=0最左, x=100最右, y=0最上, y=100最下）\n"
        "- 本图索引（下方短横线）不输出\n"
        "- target 图号必须来自项目目录\n\n"
        "输出纪律（必须严格遵守）：\n"
        "- 不要输出分析过程，不要输出你的判断步骤\n"
        "- 不要输出 ```json 代码块，不要输出 markdown，不要在 JSON 前后加任何文字\n"
        "- 没有关系就只返回[]\n"
        "- 只有证据明确时才输出，不要把模糊标记当成结果\n\n"
        "只返回JSON数组，格式：\n"
        '[{"source":"图号","target":"目标图号","relation":"index_ref|detail_ref|section_ref|elevation_ref|callout_ref",'
        '"global_pct":{"x":0,"y":0},"index_label":"索引编号或标记文字","confidence":0.0,'
        '"visual_evidence":"描述你看到的符号"}]'
    )


async def _discover_group(
    group_sheets: List[Dict[str, Any]],
    all_catalog_entries: List[Dict[str, str]],
    call_kimi,
    *,
    project_id: str | None = None,
    audit_version: int | None = None,
) -> List[Dict[str, Any]]:
    """Run AI discovery for one group of sheets."""
    # Render images for all sheets in this group
    all_images: List[bytes] = []
    evidence_service = EvidenceService(renderer=pdf_page_to_5images)
    render_options = _relationship_render_options()
    for sheet in group_sheets:
        if not sheet["pdf_path"]:
            logger.warning("关系发现跳过无PDF图纸: %s", sheet["sheet_no"])
            continue
        try:
            pack = await evidence_service.get_evidence_pack(
                EvidenceRequest(
                    pack_type=EvidencePackType.DEEP_PACK,
                    source_pdf_path=sheet["pdf_path"],
                    source_page_index=sheet["page_index"],
                    render_options=render_options,
                )
            )
            all_images.extend([
                pack.images["source_full"],
                pack.images["source_top_left"],
                pack.images["source_top_right"],
                pack.images["source_bottom_left"],
                pack.images["source_bottom_right"],
            ])
        except Exception as exc:
            logger.warning("关系发现渲染图片失败: %s (%s)", sheet["sheet_no"], exc)

    if not all_images:
        return []

    prompt_bundle = assemble_legacy_stage_prompt(
        stage_key="sheet_relationship_discovery",
        variables={
            "discovery_prompt": _build_discovery_prompt(
                group_sheets,
                all_catalog_entries,
            )
        },
        user_prompt_override=render_legacy_stage_user_prompt(
            stage_key="sheet_relationship_discovery",
            variables={
                "discovery_prompt": _build_discovery_prompt(
                    group_sheets,
                    all_catalog_entries,
                )
            },
        ),
    )
    max_tokens = _env_int("AUDIT_RELATIONSHIP_DISCOVERY_MAX_TOKENS", 8192)

    try:
        if project_id is not None and audit_version is not None and _relationship_stream_enabled():
            runner = _get_relationship_runner(
                project_id,
                audit_version,
                call_kimi=call_kimi,
            )
            turn_result: RunnerTurnResult = await runner.run_stream(
                RunnerTurnRequest(
                    agent_key="relationship_review_agent",
                    agent_name="关系审查Agent",
                    step_key="relationship_discovery",
                    progress_hint=15,
                    turn_kind="relationship_group_discovery",
                    system_prompt=prompt_bundle.system_prompt,
                    user_prompt=prompt_bundle.user_prompt,
                    images=all_images,
                    temperature=0.0,
                    max_tokens=max_tokens,
                    meta={
                        **dict(prompt_bundle.meta or {}),
                        "mode": "legacy_group",
                        "sheet_count": len(group_sheets),
                        "prompt_source": prompt_bundle.meta.get("prompt_source"),
                        "subsession_key": _relationship_subsession_key(
                            "legacy_group",
                            *[sheet.get("sheet_no", "") for sheet in group_sheets],
                        ),
                    },
                ),
                should_cancel=lambda: is_cancel_requested(project_id),
            )
            result = turn_result.output if turn_result.status == "ok" else []
        else:
            runner = _get_relationship_runner(
                project_id or "__adhoc_relationship__",
                audit_version or 0,
                call_kimi=call_kimi,
            )
            turn_result: RunnerTurnResult = await runner.run_once(
                RunnerTurnRequest(
                    agent_key="relationship_review_agent",
                    agent_name="关系审查Agent",
                    step_key="relationship_discovery",
                    progress_hint=15,
                    turn_kind="relationship_group_discovery",
                    system_prompt=prompt_bundle.system_prompt,
                    user_prompt=prompt_bundle.user_prompt,
                    images=all_images,
                    temperature=0.0,
                    max_tokens=max_tokens,
                    meta={
                        **dict(prompt_bundle.meta or {}),
                        "mode": "legacy_group",
                        "sheet_count": len(group_sheets),
                        "prompt_source": prompt_bundle.meta.get("prompt_source"),
                        "subsession_key": _relationship_subsession_key(
                            "legacy_group",
                            *[sheet.get("sheet_no", "") for sheet in group_sheets],
                        ),
                    },
                )
            )
            result = turn_result.output if turn_result.status == "ok" else []
    except AuditCancellationRequested:
        raise
    except Exception as exc:
        logger.warning("关系发现 AI 调用失败: %s", exc)
        return []

    if not isinstance(result, list):
        logger.warning("关系发现返回格式异常: type=%s", type(result).__name__)
        return []
    cleaned = [item for item in result if isinstance(item, dict)]
    report = _build_relationship_agent_report(
        turn_result,
        stage="group_discovery",
        cleaned=cleaned,
    )
    if report.blocking_issues and project_id is not None and audit_version is not None:
        append_agent_status_report(
            project_id,
            audit_version,
            step_key="relationship_discovery",
            agent_key="relationship_review_agent",
            agent_name="关系审查Agent",
            progress_hint=15,
            report=report,
        )
    return cleaned


async def _discover_relationship_task_v2(
    *,
    source_sheet: Dict[str, Any],
    target_sheet: Dict[str, Any],
    call_kimi,
    project_id: str | None,
    audit_version: int | None,
    evidence_service,
    skill_profile: Dict[str, Any],
    feedback_profile: Dict[str, Any],
    hot_sheet_registry: HotSheetRegistry | None = None,
    prompt_bundle: RuntimePromptBundle | None = None,
) -> List[Dict[str, Any]]:
    skip_reason = _should_skip_relationship_candidate_review(source_sheet, target_sheet)
    if skip_reason:
        if project_id is not None and audit_version is not None:
            append_run_event(
                project_id,
                audit_version,
                level="warning",
                step_key="relationship_discovery",
                agent_key="relationship_review_agent",
                agent_name="关系审查Agent",
                event_kind="runner_input_skipped",
                progress_hint=15,
                message="关系审查Agent 跳过了一组明显无效的候选关系，没有继续发给 AI",
                meta={
                    "reason": skip_reason,
                    "source_sheet_no": source_sheet.get("sheet_no"),
                    "target_sheet_no": target_sheet.get("sheet_no"),
                },
            )
        return []

    plans = plan_lite(
        task_type="relationship",
        source_sheet_no=source_sheet["sheet_no"],
        target_sheet_no=target_sheet["sheet_no"],
        skill_profile=skill_profile,
        feedback_profile=feedback_profile,
        priority="high",
    )
    if not plans:
        return []

    plan = plans[0]

    async def _run_plan(plan_item: EvidencePlanItem) -> List[Dict[str, Any]]:
        discovery_prompt = _build_relationship_task_prompt(source_sheet, target_sheet)
        resolved_prompt_bundle = prompt_bundle or assemble_legacy_stage_prompt(
            stage_key="sheet_relationship_discovery",
            variables={"discovery_prompt": discovery_prompt},
            user_prompt_override=discovery_prompt,
        )
        pack = await evidence_service.get_evidence_pack(
            EvidenceRequest(
                pack_type=plan_item.pack_type,
                source_pdf_path=source_sheet["pdf_path"],
                source_page_index=source_sheet["page_index"],
                target_pdf_path=target_sheet["pdf_path"],
                target_page_index=target_sheet["page_index"],
                render_options=_relationship_render_options(),
            )
        )
        if project_id is not None and audit_version is not None and _relationship_stream_enabled():
            runner = _get_relationship_runner(
                project_id,
                audit_version,
                call_kimi=call_kimi,
            )
            turn_result: RunnerTurnResult = await runner.run_stream(
                RunnerTurnRequest(
                    agent_key="relationship_review_agent",
                    agent_name="关系审查Agent",
                    step_key="relationship_discovery",
                    progress_hint=15,
                    turn_kind="relationship_candidate_review",
                    system_prompt=resolved_prompt_bundle.system_prompt,
                    user_prompt=resolved_prompt_bundle.user_prompt,
                    images=list(pack.images.values()),
                    temperature=0.0,
                    max_tokens=_env_int("AUDIT_RELATIONSHIP_DISCOVERY_MAX_TOKENS", 8192),
                    meta={
                        **dict(resolved_prompt_bundle.meta or {}),
                        "candidate_source_sheet_no": source_sheet["sheet_no"],
                        "candidate_target_sheet_no": target_sheet["sheet_no"],
                        "pack_type": plan_item.pack_type.value,
                        "prompt_source": resolved_prompt_bundle.meta.get("prompt_source"),
                        "subsession_key": _relationship_subsession_key(
                            "candidate_review",
                            source_sheet["sheet_no"],
                            target_sheet["sheet_no"],
                            plan_item.pack_type.value,
                        ),
                    },
                ),
                should_cancel=lambda: is_cancel_requested(project_id),
            )
            result = turn_result.output if turn_result.status == "ok" else []
        else:
            runner = _get_relationship_runner(
                project_id or "__adhoc_relationship__",
                audit_version or 0,
                call_kimi=call_kimi,
            )
            turn_result: RunnerTurnResult = await runner.run_once(
                RunnerTurnRequest(
                    agent_key="relationship_review_agent",
                    agent_name="关系审查Agent",
                    step_key="relationship_discovery",
                    progress_hint=15,
                    turn_kind="relationship_candidate_review",
                    system_prompt=resolved_prompt_bundle.system_prompt,
                    user_prompt=resolved_prompt_bundle.user_prompt,
                    images=list(pack.images.values()),
                    temperature=0.0,
                    max_tokens=_env_int("AUDIT_RELATIONSHIP_DISCOVERY_MAX_TOKENS", 8192),
                    meta={
                        **dict(resolved_prompt_bundle.meta or {}),
                        "candidate_source_sheet_no": source_sheet["sheet_no"],
                        "candidate_target_sheet_no": target_sheet["sheet_no"],
                        "pack_type": plan_item.pack_type.value,
                        "prompt_source": resolved_prompt_bundle.meta.get("prompt_source"),
                        "subsession_key": _relationship_subsession_key(
                            "candidate_review",
                            source_sheet["sheet_no"],
                            target_sheet["sheet_no"],
                            plan_item.pack_type.value,
                        ),
                    },
                )
            )
            result = turn_result.output if turn_result.status == "ok" else []
        if not isinstance(result, list):
            return []
        normalized = apply_relationship_runtime_policy(
            [item for item in result if isinstance(item, dict)],
            skill_profile=skill_profile,
            feedback_profile=feedback_profile,
        )
        report = _build_relationship_agent_report(
            turn_result,
            stage="candidate_review",
            source_sheet_no=source_sheet["sheet_no"],
            target_sheet_no=target_sheet["sheet_no"],
            cleaned=normalized,
        )
        if report.blocking_issues and project_id is not None and audit_version is not None:
            append_agent_status_report(
                project_id,
                audit_version,
                step_key="relationship_discovery",
                agent_key="relationship_review_agent",
                agent_name="关系审查Agent",
                progress_hint=15,
                report=report,
            )
        for item in normalized:
            item["evidence_pack_id"] = plan_item.pack_type.value
            if hot_sheet_registry is not None:
                confidence = float(item.get("confidence") or 0.0)
                hot_sheet_registry.publish(
                    item.get("source"),
                    finding_type="relationship_candidate",
                    confidence=confidence,
                    source_agent="relationship_review_agent",
                )
                hot_sheet_registry.publish(
                    item.get("target"),
                    finding_type="relationship_candidate",
                    confidence=confidence,
                    source_agent="relationship_review_agent",
                )
        return normalized

    first_round = await _run_plan(plan)
    if not first_round:
        return []

    max_confidence = max(float(item.get("confidence") or 0.0) for item in first_round)
    if not _relationship_needs_more_evidence(
        max_confidence,
        skill_profile=skill_profile,
        feedback_profile=feedback_profile,
        review_round=1,
    ):
        return attach_relationship_findings(first_round, review_round=1)

    deep_plans = plan_deep(
        task_type="relationship",
        source_sheet_no=source_sheet["sheet_no"],
        target_sheet_no=target_sheet["sheet_no"],
        current_pack_type=plan.pack_type,
        current_round=1,
        triggered_by="confidence_low",
        skill_profile=skill_profile,
        feedback_profile=feedback_profile,
        priority="high",
    )
    if not deep_plans:
        return attach_relationship_findings(
            first_round,
            review_round=3,
            triggered_by="confidence_low",
        )

    second_round = await _run_plan(deep_plans[0])
    if not second_round:
        return attach_relationship_findings(
            first_round,
            review_round=3,
            triggered_by="confidence_low",
        )

    second_confidence = max(float(item.get("confidence") or 0.0) for item in second_round)
    if _relationship_below_threshold(
        second_confidence,
        skill_profile=skill_profile,
        feedback_profile=feedback_profile,
    ):
        return attach_relationship_findings(
            second_round,
            review_round=3,
            triggered_by="confidence_low",
        )

    return attach_relationship_findings(
        second_round,
        review_round=2,
        triggered_by="confidence_low",
    )


def _validate_and_normalize(
    raw_relationships: List[Dict[str, Any]],
    valid_sheet_nos: set[str],
) -> List[Dict[str, Any]]:
    """Validate AI-discovered relationships against known sheet numbers."""
    validated: List[Dict[str, Any]] = []
    seen: set[Tuple[str, str]] = set()

    for rel in raw_relationships:
        source = str(rel.get("source", "")).strip()
        target = str(rel.get("target", "")).strip()
        if not source or not target:
            continue

        src_key = normalize_sheet_no(source)
        tgt_key = normalize_sheet_no(target)
        if not src_key or not tgt_key or src_key == tgt_key:
            continue

        # target must exist in catalog
        if tgt_key not in valid_sheet_nos:
            continue

        pair_key = (src_key, tgt_key)
        if pair_key in seen:
            continue
        seen.add(pair_key)

        raw_pct = rel.get("global_pct") if isinstance(rel.get("global_pct"), dict) else {}
        validated.append({
            "source": source,
            "target": target,
            "source_key": src_key,
            "target_key": tgt_key,
            "relation": str(rel.get("relation", "ai_visual")).strip(),
            "global_pct": {"x": float(raw_pct.get("x", 0)), "y": float(raw_pct.get("y", 0))} if raw_pct else None,
            "index_label": str(rel.get("index_label", "")).strip(),
            "confidence": float(rel.get("confidence", 0.5)),
            "visual_evidence": str(rel.get("visual_evidence", "")).strip(),
            "evidence_pack_id": str(rel.get("evidence_pack_id") or "").strip() or None,
            "finding": rel.get("finding") if isinstance(rel.get("finding"), dict) else None,
        })

    return validated


async def discover_relationships_async(
    project_id: str,
    db,
    call_kimi,
    *,
    audit_version: int | None = None,
    concurrency: int | None = None,
    sheet_filters: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Main entry: AI-driven relationship discovery across all sheets.

    Returns validated list of cross-sheet relationships with coordinates.
    """
    sheets = _load_ready_sheets(project_id, db, sheet_filters=sheet_filters)
    if not sheets:
        logger.info("关系发现: 无就绪图纸, project=%s", project_id)
        return []

    # Build catalog reference for AI
    all_catalog_entries = [
        {"图号": s["sheet_no"], "图名": s["sheet_name"]}
        for s in sheets
    ]
    valid_sheet_nos = {normalize_sheet_no(s["sheet_no"]) for s in sheets if normalize_sheet_no(s["sheet_no"])}

    # Group and batch
    groups = _group_sheets(sheets)
    resolved_concurrency = concurrency or _env_int(
        "AUDIT_RELATIONSHIP_DISCOVERY_CONCURRENCY",
        4,
    )
    logger.info(
        "关系发现开始: project=%s sheets=%s groups=%s concurrency=%s render=%s",
        project_id, len(sheets), len(groups), resolved_concurrency, _relationship_render_options(),
    )
    if audit_version is not None:
        append_run_event(
            project_id,
            audit_version,
            level="info",
            step_key="relationship_discovery",
            agent_key="relationship_review_agent",
            agent_name="关系审查Agent",
            event_kind="phase_started",
            progress_hint=12,
            message=f"关系审查Agent 开始分析跨图关系，共 {len(sheets)} 张图纸待处理",
            meta={"sheet_count": len(sheets), "group_count": len(groups)},
        )

    # Run all groups with bounded concurrency
    semaphore = asyncio.Semaphore(resolved_concurrency)
    heartbeat_seconds = _env_float("AUDIT_RELATIONSHIP_DISCOVERY_HEARTBEAT_SECONDS", 25.0)

    async def _heartbeat(group_index: int, group_count: int, stop_signal: asyncio.Event) -> None:
        if audit_version is None:
            return
        while not stop_signal.is_set():
            try:
                await asyncio.wait_for(stop_signal.wait(), timeout=heartbeat_seconds)
                return
            except asyncio.TimeoutError:
                append_run_event(
                    project_id,
                    audit_version,
                    level="warning",
                    step_key="relationship_discovery",
                    agent_key="relationship_review_agent",
                    agent_name="关系审查Agent",
                    event_kind="heartbeat",
                    progress_hint=13,
                    message=f"第 {group_index} 组图纸分析时间较长，系统仍在继续",
                    meta={"group_index": group_index, "group_count": group_count},
                )

    async def _run_group(group_index: int, group: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        async with semaphore:
            if audit_version is not None:
                append_run_event(
                    project_id,
                    audit_version,
                    level="info",
                    step_key="relationship_discovery",
                    agent_key="relationship_review_agent",
                    agent_name="关系审查Agent",
                    event_kind="phase_progress",
                    progress_hint=14,
                    message=f"关系审查Agent 正在处理第 {group_index} 组图纸，共 {len(groups)} 组",
                    meta={"group_index": group_index, "group_count": len(groups)},
                )

            stop_signal = asyncio.Event()
            heartbeat_task = asyncio.create_task(_heartbeat(group_index, len(groups), stop_signal))
            started_at = time.monotonic()
            try:
                result = await _discover_group(
                    group,
                    all_catalog_entries,
                    call_kimi,
                    project_id=project_id,
                    audit_version=audit_version,
                )
            except AuditCancellationRequested:
                raise
            except Exception:
                if audit_version is not None:
                    append_run_event(
                        project_id,
                        audit_version,
                        level="warning",
                        step_key="relationship_discovery",
                        agent_key="relationship_review_agent",
                        agent_name="关系审查Agent",
                        event_kind="warning",
                        progress_hint=15,
                        message=f"关系审查Agent 暂时没拿到第 {group_index} 组的可用结果，已经继续后续分析",
                        meta={"group_index": group_index, "group_count": len(groups)},
                    )
                raise
            finally:
                stop_signal.set()
                await heartbeat_task

            if audit_version is not None:
                elapsed_seconds = round(time.monotonic() - started_at, 1)
                relation_count = len(result)
                message = (
                    f"第 {group_index} 组图纸关系分析完成，发现 {relation_count} 处关联"
                    if relation_count > 0
                    else f"第 {group_index} 组图纸关系分析完成，暂未发现可继续审核的关联"
                )
                append_run_event(
                    project_id,
                    audit_version,
                    level="success",
                    step_key="relationship_discovery",
                    agent_key="relationship_review_agent",
                    agent_name="关系审查Agent",
                    event_kind="phase_completed",
                    progress_hint=16,
                    message=message,
                    meta={
                        "group_index": group_index,
                        "group_count": len(groups),
                        "relation_count": relation_count,
                        "elapsed_seconds": elapsed_seconds,
                    },
                )
            return result

    group_results = await asyncio.gather(
        *[_run_group(index + 1, group) for index, group in enumerate(groups)],
        return_exceptions=True,
    )

    all_raw: List[Dict[str, Any]] = []
    for i, result in enumerate(group_results):
        if isinstance(result, AuditCancellationRequested) or result.__class__.__name__ == "AuditCancellationRequested":
            raise result
        if isinstance(result, Exception):
            logger.warning("关系发现 group %s 失败: %s", i, result)
            continue
        all_raw.extend(result)

    validated = _validate_and_normalize(all_raw, valid_sheet_nos)
    logger.info(
        "关系发现完成: project=%s raw=%s validated=%s",
        project_id, len(all_raw), len(validated),
    )
    if audit_version is not None:
        append_run_event(
            project_id,
            audit_version,
            level="success",
            step_key="relationship_discovery",
            agent_key="relationship_review_agent",
            agent_name="关系审查Agent",
            event_kind="phase_completed",
            progress_hint=16,
            message=f"关系审查Agent 已完成跨图关系分析，共整理出 {len(validated)} 处跨图关联",
            meta={"validated": len(validated), "raw": len(all_raw)},
        )
    return validated


async def discover_relationships_v2_async(
    project_id: str,
    db,
    call_kimi,
    *,
    audit_version: int | None = None,
    hot_sheet_registry: HotSheetRegistry | None = None,
    sheet_filters: List[str] | None = None,
) -> List[Dict[str, Any]]:
    sheets = _load_ready_sheets(project_id, db, sheet_filters=sheet_filters)
    if not sheets:
        return []

    valid_sheet_nos = {normalize_sheet_no(s["sheet_no"]) for s in sheets if normalize_sheet_no(s["sheet_no"])}
    candidate_tasks = _build_candidate_relationship_tasks(sheets, valid_sheet_nos)
    if not candidate_tasks:
        fallback_kwargs: Dict[str, Any] = {"audit_version": audit_version}
        if sheet_filters is not None:
            fallback_kwargs["sheet_filters"] = sheet_filters
        return await discover_relationships_async(
            project_id,
            db,
            call_kimi,
            **fallback_kwargs,
        )

    skill_profile = load_runtime_skill_profile(
        db,
        skill_type="index",
        stage_key="sheet_relationship_discovery",
    )
    feedback_profile = load_feedback_runtime_profile(db, issue_type="index")
    evidence_service = get_evidence_service()

    if audit_version is not None:
        append_run_event(
            project_id,
            audit_version,
            level="info",
            step_key="relationship_discovery",
            agent_key="relationship_review_agent",
            agent_name="关系审查Agent",
            event_kind="phase_started",
            progress_hint=12,
            message=f"关系审查Agent 已整理出 {len(candidate_tasks)} 组候选关系，准备逐组复核",
            meta={"candidate_tasks": len(candidate_tasks), "sheet_count": len(sheets)},
        )

    all_raw: List[Dict[str, Any]] = []
    for index, (source_sheet, target_sheet) in enumerate(candidate_tasks, start=1):
        if not source_sheet.get("pdf_path") or not target_sheet.get("pdf_path"):
            continue
        if audit_version is not None:
            append_run_event(
                project_id,
                audit_version,
                level="info",
                step_key="relationship_discovery",
                agent_key="relationship_review_agent",
                agent_name="关系审查Agent",
                event_kind="phase_progress",
                progress_hint=14,
                message=(
                    f"关系审查Agent 正在复核第 {index} 组候选关系，"
                    f"当前核对 {source_sheet['sheet_no']} 和 {target_sheet['sheet_no']}"
                ),
                meta={
                    "candidate_index": index,
                    "candidate_total": len(candidate_tasks),
                    "source_sheet_no": source_sheet["sheet_no"],
                    "target_sheet_no": target_sheet["sheet_no"],
                },
            )
        result = await _discover_relationship_task_v2(
            source_sheet=source_sheet,
            target_sheet=target_sheet,
            call_kimi=call_kimi,
            project_id=project_id,
            audit_version=audit_version,
            evidence_service=evidence_service,
            skill_profile=skill_profile,
            feedback_profile=feedback_profile,
            hot_sheet_registry=hot_sheet_registry,
        )
        all_raw.extend(result)
        if audit_version is not None:
            append_run_event(
                project_id,
                audit_version,
                level="success",
                step_key="relationship_discovery",
                agent_key="relationship_review_agent",
                agent_name="关系审查Agent",
                event_kind="phase_progress",
                progress_hint=15,
                message=(
                    f"关系审查Agent 已完成第 {index} 组候选关系复核，"
                    f"本组整理出 {len(result)} 处关联"
                ),
                meta={
                    "candidate_index": index,
                    "candidate_total": len(candidate_tasks),
                    "relation_count": len(result),
                },
            )

    validated = _validate_and_normalize(all_raw, valid_sheet_nos)
    validated = apply_relationship_runtime_policy(
        validated,
        skill_profile=skill_profile,
        feedback_profile=feedback_profile,
    )
    if not all(isinstance(item.get("finding"), dict) for item in validated):
        validated = attach_relationship_findings(validated, review_round=1)
    if audit_version is not None:
        append_run_event(
            project_id,
            audit_version,
            level="success",
            step_key="relationship_discovery",
            agent_key="relationship_review_agent",
            agent_name="关系审查Agent",
            event_kind="phase_completed",
            progress_hint=16,
            message=f"关系审查Agent 已完成候选关系复核，共整理出 {len(validated)} 处跨图关联",
            meta={"validated": len(validated), "candidate_tasks": len(candidate_tasks)},
        )
    return validated


def discover_relationships(
    project_id: str,
    db,
    *,
    audit_version: int | None = None,
    sheet_filters: List[str] | None = None,
) -> List[Dict[str, Any]]:
    """Synchronous wrapper for discover_relationships_async."""
    from services.ai_service import call_kimi
    kwargs: Dict[str, Any] = {}
    if audit_version is not None:
        kwargs["audit_version"] = audit_version
    if sheet_filters is not None:
        kwargs["sheet_filters"] = sheet_filters
    return asyncio.run(discover_relationships_async(project_id, db, call_kimi, **kwargs))


def discover_relationships_v2(
    project_id: str,
    db,
    *,
    audit_version: int | None = None,
    hot_sheet_registry: HotSheetRegistry | None = None,
    sheet_filters: List[str] | None = None,
) -> List[Dict[str, Any]]:
    from services.ai_service import call_kimi
    kwargs: Dict[str, Any] = {}
    if audit_version is not None:
        kwargs["audit_version"] = audit_version
    if hot_sheet_registry is not None:
        kwargs["hot_sheet_registry"] = hot_sheet_registry
    if sheet_filters is not None:
        kwargs["sheet_filters"] = sheet_filters
    return asyncio.run(discover_relationships_v2_async(project_id, db, call_kimi, **kwargs))


def save_ai_edges(project_id: str, relationships: List[Dict[str, Any]], db) -> int:
    """Save AI-discovered relationships as SheetEdge rows with edge_type='ai_visual'.

    Clears existing ai_visual edges for this project before saving.
    """
    db.query(SheetEdge).filter(
        SheetEdge.project_id == project_id,
        SheetEdge.edge_type == "ai_visual",
    ).delete(synchronize_session=False)
    count = 0
    for rel in relationships:
        edge = SheetEdge(
            project_id=project_id,
            source_sheet_no=rel["source"],
            target_sheet_no=rel["target"],
            edge_type="ai_visual",
            confidence=rel.get("confidence", 0.5),
            evidence_json=json.dumps(
                {
                    "relation": rel.get("relation", ""),
                    "global_pct": rel.get("global_pct"),
                    "index_label": rel.get("index_label", ""),
                    "visual_evidence": rel.get("visual_evidence", ""),
                    "source": "ai_relationship_discovery",
                },
                ensure_ascii=False,
            ),
        )
        db.add(edge)
        count += 1
    db.commit()
    return count
