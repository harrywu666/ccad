"""Material audit implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from domain.sheet_normalization import normalize_sheet_no
from domain.text_cleaning import strip_mtext_formatting
from models import AuditResult, Drawing, JsonData
from services.ai_prompt_service import resolve_stage_system_prompt_with_skills
from services.audit.common import build_anchor, to_evidence_json
from services.audit.prompt_builder import build_material_review_prompt, compact_material_rows
from services.audit_runtime.agent_reports import MaterialAgentReport
from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.contracts import EvidencePack, EvidencePackType, EvidenceRequest
from services.audit_runtime.evidence_planner import plan_evidence_requests
from services.audit_runtime.evidence_service import get_evidence_service
from services.audit_runtime.finding_schema import Finding, GroundingRequiredError, apply_finding_to_audit_result
from services.audit_runtime.hot_sheet_registry import HotSheetRegistry
from services.audit_runtime.providers.factory import build_runner_provider
from services.audit_runtime.review_task_schema import WorkerResultCard, WorkerTaskCard
from services.audit_runtime.runner_types import RunnerTurnRequest, RunnerTurnResult
from services.audit_runtime.cancel_registry import AuditCancellationRequested, is_cancel_requested
from services.audit_runtime.state_transitions import (
    append_agent_status_report,
    append_result_upsert_events,
    append_run_event,
)
from services.coordinate_service import enrich_json_with_coordinates
from services.feedback_runtime_service import load_feedback_runtime_profile
from services.kimi_service import call_kimi, call_kimi_stream
from services.skill_pack_service import load_runtime_skill_profile

logger = logging.getLogger(__name__)


def _material_issue_evidence(issue: AuditResult) -> Dict[str, Any]:
    try:
        payload = json.loads(str(issue.evidence_json or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        payload = {}
    anchors = list(payload.get("anchors") or [])
    anchor = dict(anchors[0] or {}) if anchors else {}
    return {
        "sheet_no": str(anchor.get("sheet_no") or issue.sheet_no_a or "UNKNOWN").strip() or "UNKNOWN",
        "location": str(anchor.get("grid") or issue.location or "未定位").strip() or "未定位",
        "rule_id": str(issue.rule_id or _material_rule_id(issue.location, issue.description)).strip(),
        "evidence_pack_id": str(issue.evidence_pack_id or "focus_pack").strip() or "focus_pack",
        "description": str(issue.description or "").strip(),
        "severity": str(issue.severity or "warning").strip().lower() or "warning",
    }


def _material_worker_result_from_issues(task: WorkerTaskCard, issues: List[AuditResult]) -> WorkerResultCard:
    if not issues:
        return WorkerResultCard(
            task_id=task.id,
            hypothesis_id=task.hypothesis_id,
            worker_kind=task.worker_kind,
            status="rejected",
            confidence=0.74,
            summary=f"旧材料审查入口已作为 worker 包装层执行，{task.source_sheet_no} 未发现材料问题",
            meta={
                "compat_mode": "worker_wrapper",
                "sheet_no": task.source_sheet_no,
                "location": task.objective,
                "rule_id": "material_consistency_review",
                "evidence_pack_id": "focus_pack",
                "issue_count": 0,
            },
        )

    evidence = [_material_issue_evidence(issue) for issue in issues[:5]]
    first = evidence[0]
    confidence_values = [
        float(issue.confidence)
        for issue in issues
        if isinstance(issue.confidence, (int, float))
    ]
    confidence = max(confidence_values) if confidence_values else 0.83
    return WorkerResultCard(
        task_id=task.id,
        hypothesis_id=task.hypothesis_id,
        worker_kind=task.worker_kind,
        status="confirmed",
        confidence=confidence,
        summary=str(issues[0].description or f"旧材料审查入口返回 {len(issues)} 处材料问题").strip(),
        evidence=evidence,
        meta={
            "compat_mode": "worker_wrapper",
            "sheet_no": first["sheet_no"],
            "location": first["location"],
            "rule_id": first["rule_id"],
            "evidence_pack_id": first["evidence_pack_id"],
            "severity": first["severity"],
            "issue_count": len(issues),
            "review_round": max(int(issue.review_round or 1) for issue in issues),
        },
    )


def run_material_worker_wrapper(
    project_id: str,
    audit_version: int,
    db,
    task: WorkerTaskCard,
) -> WorkerResultCard:
    issues = audit_materials(
        project_id,
        audit_version,
        db,
        sheet_filters=[task.source_sheet_no] if str(task.source_sheet_no or "").strip() else None,
    )
    return _material_worker_result_from_issues(task, issues)


def _build_material_agent_report(
    turn_result: RunnerTurnResult,
    *,
    sheet_no: str,
    cleaned: List[Dict[str, Any]],
) -> MaterialAgentReport:
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
                "stage": "material_review",
                "sheet_no": str(sheet_no or "").strip(),
                "reason": turn_result.error or "runner_output_unstable",
            }
        )

    if blocking_issues:
        help_request = "restart_subsession"
        next_action = "rerun_current_batch"
        confidence = 0.35
    else:
        help_request = ""
        next_action = "continue"
        confidence = 0.84 if cleaned else 0.6

    return MaterialAgentReport(
        batch_summary=f"材料审查Agent 已完成一批材料一致性检查（{sheet_no or 'UNKNOWN'}）",
        confirmed_findings=[],
        suspected_findings=[],
        blocking_issues=blocking_issues,
        runner_help_request=help_request,
        agent_confidence=confidence,
        next_recommended_action=next_action,
    )


def _get_material_runner(
    project_id: str,
    audit_version: int,
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


def _material_confidence_for_severity(severity: str) -> float:
    normalized = str(severity or "warning").strip().lower()
    if normalized == "error":
        return 0.85
    if normalized == "info":
        return 0.6
    return 0.72


def _material_rule_id(location: Optional[str], description: Optional[str]) -> str:
    text = f"{location or ''} {description or ''}"
    if "未找到定义" in text:
        return "material_missing_definition"
    if "未使用" in text:
        return "material_unused_table_entry"
    if "命名不一致" in text:
        return "material_name_conflict"
    if "高度相似" in text:
        return "material_similarity_conflict"
    return "material_consistency_review"


def _apply_material_finding(
    issue: AuditResult,
    *,
    review_round: int = 1,
    triggered_by: str | None = None,
) -> AuditResult:
    confidence = _material_confidence_for_severity(issue.severity or "warning")
    status = "confirmed" if confidence >= 0.75 else "suspected"
    finding = Finding(
        sheet_no=str(issue.sheet_no_a or issue.sheet_no_b or "UNKNOWN").strip() or "UNKNOWN",
        location=str(issue.location or "未定位").strip() or "未定位",
        rule_id=_material_rule_id(issue.location, issue.description),
        finding_type="material_conflict",
        severity=str(issue.severity or "warning").strip().lower() or "warning",
        status=status,  # type: ignore[arg-type]
        confidence=confidence,
        source_agent="material_review_agent",
        evidence_pack_id="focus_pack",
        review_round=review_round,
        triggered_by=triggered_by,
        description=str(issue.description or "").strip(),
    )
    return apply_finding_to_audit_result(issue, finding, require_grounding=True)


def _material_v2_enabled() -> bool:
    return str(os.getenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _material_stream_enabled() -> bool:
    raw = os.getenv("AUDIT_KIMI_STREAM_ENABLED")
    if raw is None:
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _append_material_stream_event(
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
        step_key="material",
        agent_key="material_review_agent",
        agent_name="材料审查Agent",
        event_kind=event_kind,
        progress_hint=progress_hint,
        message=message,
        meta=meta or {},
    )


def _material_agent_concurrency() -> int:
    raw = os.getenv("MATERIAL_AGENT_CONCURRENCY", "6")
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return 6
    return max(1, min(16, value))


def _norm_material_code(value: Optional[str]) -> str:
    if not value:
        return ""
    text = str(value).strip().upper()
    text = re.sub(r"[\s\-_./\\()（）【】\[\]{}:：|]+", "", text)
    return text


def _norm_material_name(value: Optional[str]) -> str:
    if not value:
        return ""
    text = str(value).strip()
    text = re.sub(r"\s+", "", text)
    return text


def _is_valid_material_code(code_key: str) -> bool:
    if not code_key:
        return False
    if len(code_key) > 12:
        return False
    if not any(ch.isalpha() for ch in code_key):
        return False
    if not any(ch.isdigit() for ch in code_key):
        return False
    return re.match(r"^[A-Z]*\d+[A-Z0-9]*$", code_key) is not None


def resolve_material_issue_severity(
    severity: str,
    *,
    skill_profile: Dict[str, Any] | None = None,
    feedback_profile: Dict[str, Any] | None = None,
) -> str:
    base = str(severity or "warning").strip().lower() or "warning"
    override = None
    skill_policy = ((skill_profile or {}).get("judgement_policy") or {}).get("material")
    if isinstance(skill_policy, dict):
        raw_override = str(skill_policy.get("severity_override") or "").strip().lower()
        if raw_override:
            override = raw_override
    if not override:
        raw_override = str((feedback_profile or {}).get("severity_override") or "").strip().lower()
        if raw_override:
            override = raw_override
    if not override:
        hint = (feedback_profile or {}).get("experience_hint")
        if isinstance(hint, dict) and str(hint.get("intervention_level") or "").strip().lower() in {"soft", "hard"}:
            override = "warning"
    return override or base


async def _run_material_ai_review(
    *,
    sheet_no: str,
    material_table: List[Dict[str, Any]],
    material_used: List[Dict[str, Any]],
    project_id: str | None = None,
    audit_version: int | None = None,
    pdf_path: Optional[str] = None,
    page_index: Optional[int] = None,
    images_override: Optional[List[bytes]] = None,
) -> List[Dict[str, Any]]:
    images: Optional[list] = images_override
    if images is None and pdf_path and page_index is not None:
        try:
            pack_type = EvidencePackType.OVERVIEW_PACK
            if _material_v2_enabled():
                plans = plan_evidence_requests(
                    task_type="material",
                    source_sheet_no=sheet_no,
                    requires_visual=True,
                    priority="normal",
                )
                if plans:
                    pack_type = plans[0].pack_type

            pack = await get_evidence_service().get_evidence_pack(
                EvidenceRequest(
                    pack_type=pack_type,
                    source_pdf_path=pdf_path,
                    source_page_index=page_index,
                )
            )
            images = list(pack.images.values())
        except Exception:
            pass

    if project_id is not None and audit_version is not None and _material_stream_enabled():
        runner = _get_material_runner(project_id, audit_version)
        turn_result: RunnerTurnResult = await runner.run_stream(
            RunnerTurnRequest(
                agent_key="material_review_agent",
                agent_name="材料审查Agent",
                step_key="material",
                progress_hint=36,
                turn_kind="material_consistency_review",
                system_prompt=resolve_stage_system_prompt_with_skills(
                    "material_consistency_review",
                    "material",
                ),
                user_prompt=build_material_review_prompt(
                    sheet_no,
                    compact_material_rows(material_table),
                    compact_material_rows(material_used),
                ),
                images=images or [],
                temperature=0.0,
                meta={"sheet_no": sheet_no, "material_rows": len(material_table), "used_rows": len(material_used)},
            ),
            should_cancel=lambda: is_cancel_requested(project_id),
        )
        result = turn_result.output if turn_result.status == "ok" else []
    else:
        runner = _get_material_runner(project_id or "__adhoc_material__", audit_version or 0)
        turn_result: RunnerTurnResult = await runner.run_once(
            RunnerTurnRequest(
                agent_key="material_review_agent",
                agent_name="材料审查Agent",
                step_key="material",
                progress_hint=36,
                turn_kind="material_consistency_review",
                system_prompt=resolve_stage_system_prompt_with_skills(
                    "material_consistency_review",
                    "material",
                ),
                user_prompt=build_material_review_prompt(
                    sheet_no,
                    compact_material_rows(material_table),
                    compact_material_rows(material_used),
                ),
                images=images or [],
                temperature=0.0,
                meta={"sheet_no": sheet_no, "material_rows": len(material_table), "used_rows": len(material_used)},
            )
        )
        result = turn_result.output if turn_result.status == "ok" else []
    if not isinstance(result, list):
        return []
    cleaned = [item for item in result if isinstance(item, dict)]
    report = _build_material_agent_report(
        turn_result,
        sheet_no=sheet_no,
        cleaned=cleaned,
    )
    if report.blocking_issues and project_id is not None and audit_version is not None:
        append_agent_status_report(
            project_id,
            audit_version,
            step_key="material",
            agent_key="material_review_agent",
            agent_name="材料审查Agent",
            progress_hint=36,
            report=report,
        )
    return cleaned


async def _prepare_material_images(job: Dict[str, Any]) -> Optional[List[bytes]]:
    pdf_path = job.get("pdf_path")
    page_index = job.get("page_index")
    if not pdf_path or page_index is None:
        return None

    pack_type = EvidencePackType.OVERVIEW_PACK
    if _material_v2_enabled():
        plans = plan_evidence_requests(
            task_type="material",
            source_sheet_no=job["sheet_no"],
            requires_visual=True,
            priority="normal",
        )
        if plans:
            pack_type = plans[0].pack_type

    pack = await get_evidence_service().get_evidence_pack(
        EvidenceRequest(
            pack_type=pack_type,
            source_pdf_path=pdf_path,
            source_page_index=page_index,
        )
    )
    return list(pack.images.values())


async def _run_material_ai_reviews_bounded(
    ai_review_jobs: List[Dict[str, Any]],
    review_fn,
) -> List[List[Dict[str, Any]]]:
    if not ai_review_jobs:
        return []

    semaphore = asyncio.Semaphore(_material_agent_concurrency())

    async def _worker(job: Dict[str, Any]) -> List[Dict[str, Any]]:
        async with semaphore:
            images_override = None
            try:
                images_override = await _prepare_material_images(job)
            except Exception:
                images_override = None
            return await review_fn(
                sheet_no=job["sheet_no"],
                material_table=job["material_table"],
                material_used=job["material_used"],
                project_id=job.get("project_id"),
                audit_version=job.get("audit_version"),
                pdf_path=job.get("pdf_path"),
                page_index=job.get("page_index"),
                images_override=images_override,
            )

    results = await asyncio.gather(*[_worker(job) for job in ai_review_jobs], return_exceptions=True)
    out: List[List[Dict[str, Any]]] = []
    for r in results:
        if isinstance(r, AuditCancellationRequested):
            raise r
        if isinstance(r, Exception):
            logger.warning("材料 AI 审核降级为规则模式：error=%s", r)
            out.append([])
        else:
            out.append(r)
    return out


def _collect_material_rule_issues_and_ai_jobs(
    project_id: str,
    audit_version: int,
    db,
    *,
    sheet_filters: Optional[List[str]] = None,
) -> tuple[List[AuditResult], List[Dict[str, Any]]]:
    allowed_sheet_keys: Optional[set[str]] = None
    if sheet_filters:
        allowed_sheet_keys = {
            normalize_sheet_no(item) for item in sheet_filters if normalize_sheet_no(item)
        }
        if not allowed_sheet_keys:
            return [], []

    json_list = (
        db.query(JsonData)
        .filter(
            JsonData.project_id == project_id,
            JsonData.is_latest == 1,
        )
        .all()
    )

    rule_issues: List[AuditResult] = []
    ai_review_jobs: List[Dict[str, Any]] = []
    seen_keys: set[tuple[str, str, str]] = set()

    def append_rule_issue(issue: AuditResult) -> None:
        key = (
            str(issue.sheet_no_a or "").strip(),
            str(issue.location or "").strip(),
            str(issue.description or "").strip(),
        )
        if key in seen_keys:
            return
        seen_keys.add(key)
        rule_issues.append(issue)

    for json_data in json_list:
        if allowed_sheet_keys is not None:
            current_key = normalize_sheet_no(json_data.sheet_no)
            if not current_key or current_key not in allowed_sheet_keys:
                continue
        if not json_data.json_path:
            continue

        try:
            with open(json_data.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        data = enrich_json_with_coordinates(data)

        raw_table = data.get("material_table", []) or []
        raw_used = data.get("materials", []) or []

        material_anchor_by_code: Dict[str, Dict[str, Any]] = {}
        material_table_anchor_by_code: Dict[str, Dict[str, Any]] = {}
        for mat in raw_used:
            code_raw = str(mat.get("code", "") or "").strip()
            code_key = _norm_material_code(code_raw)
            if not _is_valid_material_code(code_key):
                continue
            if code_key in material_anchor_by_code:
                continue
            anchor = build_anchor(
                role="single",
                sheet_no=json_data.sheet_no,
                grid=str(mat.get("grid") or "").strip(),
                global_pct=mat.get("global_pct") if isinstance(mat.get("global_pct"), dict) else None,
                confidence=1.0,
                origin="material",
                highlight_region=mat.get("highlight_region") if isinstance(mat.get("highlight_region"), dict) else None,
                meta={"material_code": code_raw or None},
            )
            if anchor:
                material_anchor_by_code[code_key] = anchor

        table_map: Dict[str, Dict[str, str]] = {}
        for item in raw_table:
            code_raw = str(item.get("code", "") or "").strip()
            name_raw = strip_mtext_formatting(str(item.get("name", "") or ""))
            code_key = _norm_material_code(code_raw)
            if not _is_valid_material_code(code_key):
                continue
            if code_key not in table_map:
                table_map[code_key] = {"code": code_raw, "name": name_raw}
            table_anchor = build_anchor(
                role="single",
                sheet_no=json_data.sheet_no,
                grid=str(item.get("grid") or "").strip(),
                global_pct=item.get("global_pct") if isinstance(item.get("global_pct"), dict) else None,
                confidence=1.0,
                origin="material_table",
                highlight_region=item.get("highlight_region") if isinstance(item.get("highlight_region"), dict) else None,
                meta={"material_code": code_raw or None},
            )
            if table_anchor and code_key not in material_table_anchor_by_code:
                material_table_anchor_by_code[code_key] = table_anchor

        used_map: Dict[str, Dict[str, str]] = {}
        for item in raw_used:
            code_raw = str(item.get("code", "") or "").strip()
            name_raw = strip_mtext_formatting(str(item.get("name", "") or ""))
            code_key = _norm_material_code(code_raw)
            if not _is_valid_material_code(code_key):
                continue
            if code_key not in used_map:
                used_map[code_key] = {"code": code_raw, "name": name_raw}

        for code_key, used_item in used_map.items():
            if code_key in table_map:
                continue
            anchor = material_anchor_by_code.get(code_key)
            append_rule_issue(
                AuditResult(
                    project_id=project_id,
                    audit_version=audit_version,
                    type="material",
                    severity="error",
                    sheet_no_a=json_data.sheet_no,
                    location=f"材料标注{used_item['code']}",
                    description=(
                        f"图纸{json_data.sheet_no}中使用了材料编号{used_item['code']}（{used_item['name'] or '未命名'}），"
                        "但材料表中未找到定义。"
                    ),
                    evidence_json=to_evidence_json(
                        [anchor] if anchor else [],
                        unlocated_reason=None if anchor else "material_used_without_location",
                    ),
                )
            )

        for code_key, table_item in table_map.items():
            if code_key in used_map:
                continue
            table_anchor = material_table_anchor_by_code.get(code_key)
            append_rule_issue(
                AuditResult(
                    project_id=project_id,
                    audit_version=audit_version,
                    type="material",
                    severity="info",
                    sheet_no_a=json_data.sheet_no,
                    location=f"材料表{table_item['code']}",
                    description=(
                        f"材料表中定义了材料编号{table_item['code']}（{table_item['name'] or '未命名'}），"
                        "但在图纸标注中未使用。"
                    ),
                    evidence_json=to_evidence_json(
                        [table_anchor] if table_anchor else [],
                        unlocated_reason=None if table_anchor else "material_table_only_no_anchor",
                    ),
                )
            )

        for code_key, used_item in used_map.items():
            table_item = table_map.get(code_key)
            if not table_item:
                continue
            used_name = _norm_material_name(used_item.get("name"))
            table_name = _norm_material_name(table_item.get("name"))
            if not used_name or not table_name or used_name == table_name:
                continue
            similarity = SequenceMatcher(None, used_name, table_name).ratio()
            if similarity >= 0.92:
                continue
            anchor = material_anchor_by_code.get(code_key)
            append_rule_issue(
                AuditResult(
                    project_id=project_id,
                    audit_version=audit_version,
                    type="material",
                    severity="warning",
                    sheet_no_a=json_data.sheet_no,
                    location=f"材料编号{used_item['code']}",
                    description=(
                        f"图纸中材料编号{used_item['code']}名称为「{used_item['name'] or '未命名'}」，"
                        f"材料表中同编号名称为「{table_item['name'] or '未命名'}」，请确认是否命名不一致。"
                    ),
                    evidence_json=to_evidence_json(
                        [anchor] if anchor else [],
                        unlocated_reason=None if anchor else "material_name_conflict_unlocated",
                    ),
                )
            )

        for used_key, used_item in used_map.items():
            used_name = _norm_material_name(used_item.get("name"))
            if len(used_name) < 2:
                continue
            for table_key, table_item in table_map.items():
                if used_key == table_key:
                    continue
                table_name = _norm_material_name(table_item.get("name"))
                if len(table_name) < 2:
                    continue
                ratio = SequenceMatcher(None, used_name, table_name).ratio()
                if ratio < 0.95:
                    continue
                anchor = material_anchor_by_code.get(used_key)
                append_rule_issue(
                    AuditResult(
                        project_id=project_id,
                        audit_version=audit_version,
                        type="material",
                        severity="warning",
                        sheet_no_a=json_data.sheet_no,
                        location=f"材料标注{used_item['code']}",
                        description=(
                            f"图纸中材料「{used_item['name'] or '未命名'}」编号为{used_item['code']}，"
                            f"与材料表中「{table_item['name'] or '未命名'}」编号{table_item['code']}高度相似，"
                            "可能存在编号或命名冲突。"
                        ),
                        evidence_json=to_evidence_json(
                            [anchor] if anchor else [],
                            unlocated_reason=None if anchor else "material_similarity_unlocated",
                        ),
                    )
                )
                break

        drawing_row = (
            db.query(Drawing)
            .filter(
                Drawing.project_id == project_id,
                Drawing.catalog_id == json_data.catalog_id,
                Drawing.replaced_at == None,
            )
            .first()
        )
        sheet_pdf_path = ""
        sheet_page_index = 0
        if drawing_row:
            sheet_pdf_path = getattr(drawing_row, "pdf_path", None) or ""
            sheet_page_index = getattr(drawing_row, "page_index", None) or 0
            if not sheet_pdf_path:
                from pathlib import Path as _Path

                png_dir = _Path(getattr(drawing_row, "png_path", None) or "").expanduser().resolve().parent
                pdfs = sorted(png_dir.glob("*.pdf"), key=lambda p: p.stat().st_mtime, reverse=True) if png_dir.exists() else []
                if pdfs:
                    sheet_pdf_path = str(pdfs[0])

        if raw_table or raw_used:
            ai_review_jobs.append({
                "project_id": project_id,
                "audit_version": audit_version,
                "sheet_no": json_data.sheet_no or "",
                "material_table": raw_table,
                "material_used": raw_used,
                "material_anchor_by_code": material_anchor_by_code,
                "pdf_path": sheet_pdf_path,
                "page_index": sheet_page_index,
            })

    return rule_issues, ai_review_jobs


# 功能说明：执行材料审核主函数，检查材料表中材料定义和使用的一致性
def audit_materials(
    project_id: str,
    audit_version: int,
    db,
    sheet_filters: Optional[List[str]] = None,
    hot_sheet_registry: HotSheetRegistry | None = None,
) -> List[AuditResult]:
    skill_profile = load_runtime_skill_profile(
        db,
        skill_type="material",
        stage_key="material_consistency_review",
    )
    feedback_profile = load_feedback_runtime_profile(db, issue_type="material")
    if hot_sheet_registry is not None and sheet_filters:
        sheet_filters = list(
            hot_sheet_registry.sort_sheet_items(
                list(sheet_filters),
                lambda item: item,
            )
        )

    issues: List[AuditResult] = []
    seen_keys: set[tuple[str, str, str]] = set()

    def append_issue(issue: AuditResult) -> None:
        key = (
            str(issue.sheet_no_a or "").strip(),
            str(issue.location or "").strip(),
            str(issue.description or "").strip(),
        )
        if key in seen_keys:
            return
        seen_keys.add(key)
        try:
            _apply_material_finding(issue)
        except GroundingRequiredError:
            append_agent_status_report(
                project_id,
                audit_version,
                step_key="material",
                agent_key="material_review_agent",
                agent_name="材料审查Agent",
                progress_hint=62,
                report=MaterialAgentReport(
                    batch_summary="材料问题已经识别出来，但这次没把图上的精确位置框稳，Runner 正在帮它重启后重试。",
                    blocking_issues=[
                        {
                            "issue_type": "grounding_missing",
                            "sheet_no": issue.sheet_no_a or issue.sheet_no_b,
                            "location": issue.location,
                            "reason": "missing_highlight_region",
                        }
                    ],
                    runner_help_request="restart_subsession",
                    agent_confidence=0.0,
                    next_recommended_action="restart_subsession",
                ),
            )
            return
        db.add(issue)
        issues.append(issue)
    rule_issues, ai_review_jobs = _collect_material_rule_issues_and_ai_jobs(
        project_id,
        audit_version,
        db,
        sheet_filters=sheet_filters,
    )
    for issue in rule_issues:
        append_issue(issue)

    if ai_review_jobs:
        try:
            all_ai_results = asyncio.run(
                _run_material_ai_reviews_bounded(ai_review_jobs, _run_material_ai_review)
            )
        except Exception as exc:
            logger.warning("材料 AI 审核批量降级为规则模式：error=%s", exc)
            all_ai_results = [[] for _ in ai_review_jobs]

        for job, ai_items in zip(ai_review_jobs, all_ai_results):
            anchor_map = job["material_anchor_by_code"]
            for item in ai_items:
                severity = resolve_material_issue_severity(
                    str(item.get("severity") or "warning").strip() or "warning",
                    skill_profile=skill_profile,
                    feedback_profile=feedback_profile,
                )
                location = str(item.get("location") or f"材料{item.get('material_code') or '?'}").strip()
                description = str(item.get("description") or "").strip()
                if not description:
                    continue
                evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
                code_key = _norm_material_code(
                    str(item.get("material_code") or evidence.get("code") or "").strip()
                )
                anchor = anchor_map.get(code_key)
                issue = AuditResult(
                    project_id=project_id,
                    audit_version=audit_version,
                    type="material",
                    severity=severity,
                    sheet_no_a=job["sheet_no"],
                    location=location,
                    description=description,
                    evidence_json=to_evidence_json(
                        [anchor] if anchor else [],
                        unlocated_reason=None if anchor else "material_ai_issue_unlocated",
                    ),
                )
                append_issue(issue)

    db.commit()
    append_result_upsert_events(
        project_id,
        audit_version,
        issue_ids=[issue.id for issue in issues],
    )
    if hot_sheet_registry is not None:
        for issue in issues:
            hot_sheet_registry.publish(
                issue.sheet_no_a,
                finding_type=getattr(issue, "finding_type", None) or "material_conflict",
                confidence=float(getattr(issue, "confidence", None) or _material_confidence_for_severity(issue.severity)),
                source_agent="material_review_agent",
            )
    return issues
