"""Index audit implementation."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from domain.sheet_normalization import normalize_index_no, normalize_sheet_no
from models import AuditResult, Catalog, Drawing, JsonData
from services.ai_prompt_service import (
    resolve_stage_prompts,
    resolve_stage_system_prompt_with_skills,
)
from services.audit.common import build_anchor, to_evidence_json
from services.audit.issue_preview import ensure_issue_drawing_matches
from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.contracts import EvidenceRequest
from services.audit_runtime.evidence_planner import plan_evidence_requests
from services.audit_runtime.evidence_service import get_evidence_service
from services.audit_runtime.finding_schema import Finding, apply_finding_to_audit_result
from services.audit_runtime.hot_sheet_registry import HotSheetRegistry
from services.audit_runtime.providers.kimi_api_provider import KimiApiProvider
from services.audit_runtime.runner_types import RunnerTurnRequest, RunnerTurnResult
from services.audit_runtime.cancel_registry import AuditCancellationRequested, is_cancel_requested
from services.audit_runtime.state_transitions import append_run_event
from services.feedback_runtime_service import load_feedback_runtime_profile
from services.kimi_service import call_kimi, call_kimi_stream
from services.layout_json_service import load_enriched_layout_json
from services.skill_pack_service import (
    build_index_alias_map,
    canonicalize_index_key,
    canonicalize_sheet_key,
    load_active_skill_rules,
    load_runtime_skill_profile,
)


def _get_index_runner(
    project_id: str,
    audit_version: int,
) -> ProjectAuditAgentRunner:
    return ProjectAuditAgentRunner.get_or_create(
        project_id,
        audit_version=audit_version,
        provider=KimiApiProvider(
            run_once_func=call_kimi,
            run_stream_func=call_kimi_stream,
        ),
        shared_context={"project_id": project_id, "audit_version": audit_version},
    )


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _index_ai_review_enabled() -> bool:
    return _env_bool(
        "AUDIT_INDEX_AI_REVIEW_ENABLED",
        default=_env_bool("AUDIT_ORCHESTRATOR_V2_ENABLED", False),
    )


def _index_stream_enabled() -> bool:
    raw = os.getenv("AUDIT_KIMI_STREAM_ENABLED")
    if raw is None:
        return True
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


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
            "pdf_path": _find_pdf_in_png_dir(latest.png_path or ""),
            "page_index": latest.page_index,
        }
    return asset_map


def _run_async(coro):  # noqa: ANN001
    try:
        return asyncio.run(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()


def _reviewable_index_issue(kind: str) -> bool:
    return kind in {
        "missing_target_index_no",
        "missing_reverse_link",
        "orphan_index_without_target",
    }


def _resolve_index_review_policy(
    *,
    skill_profile: Dict[str, Any] | None = None,
    feedback_profile: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    floor = 0.0
    severity_override = (feedback_profile or {}).get("severity_override")
    skill_policy = ((skill_profile or {}).get("judgement_policy") or {}).get("index")
    if isinstance(skill_policy, dict):
        raw_floor = skill_policy.get("confidence_floor")
        if isinstance(raw_floor, (int, float)):
            floor = max(floor, float(raw_floor))
        raw_override = str(skill_policy.get("severity_override") or "").strip().lower()
        if raw_override in {"warning", "error", "info"}:
            severity_override = raw_override
    hint = (feedback_profile or {}).get("experience_hint")
    if isinstance(hint, dict):
        raw_floor = hint.get("confidence_floor")
        if isinstance(raw_floor, (int, float)):
            floor = max(floor, float(raw_floor))
        if not severity_override and str(hint.get("intervention_level") or "").strip().lower() in {"soft", "hard"}:
            severity_override = "warning"
    raw_feedback_floor = (feedback_profile or {}).get("confidence_floor")
    if isinstance(raw_feedback_floor, (int, float)):
        floor = max(floor, float(raw_feedback_floor))
    return {
        "confidence_floor": floor,
        "severity_override": severity_override,
        "reason_template": hint.get("reason_template") if isinstance(hint, dict) else None,
    }


def _index_finding_type(review_kind: str) -> str:
    mapping = {
        "missing_target_sheet": "missing_ref",
        "missing_target_index_no": "missing_ref",
        "missing_reverse_link": "missing_ref",
        "orphan_index_without_target": "missing_ref",
    }
    return mapping.get(review_kind, "missing_ref")


def _apply_index_finding(issue: AuditResult, candidate: Dict[str, Any]) -> AuditResult:
    review_round = int(candidate.get("review_round") or 1)
    confidence = float(candidate.get("review_confidence") or (0.85 if issue.severity == "error" else 0.65))
    status = "needs_review" if review_round >= 3 else ("confirmed" if confidence >= 0.8 else "suspected")
    finding = Finding(
        sheet_no=str(issue.sheet_no_a or issue.sheet_no_b or "UNKNOWN").strip() or "UNKNOWN",
        location=str(issue.location or "未定位").strip() or "未定位",
        rule_id=str(candidate.get("review_kind") or "index_review").strip(),
        finding_type=_index_finding_type(str(candidate.get("review_kind") or "")),
        severity=str(issue.severity or "warning").strip().lower() or "warning",
        status=status,  # type: ignore[arg-type]
        confidence=max(0.0, min(1.0, confidence)),
        source_agent="index_review_agent",
        evidence_pack_id=str(candidate.get("evidence_pack_id") or "overview_pack"),
        review_round=review_round,
        triggered_by=candidate.get("triggered_by"),
        description=str(issue.description or "").strip(),
    )
    return apply_finding_to_audit_result(issue, finding)


def _merge_index_ai_review(issue: AuditResult, result: Dict[str, Any]) -> None:
    try:
        payload = json.loads(issue.evidence_json or "{}")
    except Exception:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    payload["ai_review"] = {
        "decision": str(result.get("decision") or "").strip().lower(),
        "confidence": result.get("confidence"),
        "reason": str(result.get("reason") or "").strip(),
    }
    issue.evidence_json = json.dumps(payload, ensure_ascii=False)


async def _run_index_ai_review(
    candidate: Dict[str, Any],
    *,
    project_id: str | None = None,
    audit_version: int | None = None,
    asset_map: Dict[str, Dict[str, Any]],
    skill_profile: Dict[str, Any],
) -> Dict[str, Any] | None:
    source_asset = asset_map.get(candidate["source_key"]) or {}
    source_pdf_path = source_asset.get("pdf_path")
    source_page_index = source_asset.get("page_index")
    if not source_pdf_path or source_page_index is None:
        return None

    target_pdf_path = None
    target_page_index = None
    if candidate.get("target_sheet_no"):
        target_asset = asset_map.get(candidate.get("target_key") or "") or {}
        target_pdf_path = target_asset.get("pdf_path")
        target_page_index = target_asset.get("page_index")
        if not target_pdf_path or target_page_index is None:
            return None

    plans = plan_evidence_requests(
        task_type="index",
        source_sheet_no=candidate["source_sheet_no"],
        target_sheet_no=candidate.get("target_sheet_no"),
        reason=candidate["issue"].description,
    )
    if not plans:
        return None

    pack = await get_evidence_service().get_evidence_pack(
        EvidenceRequest(
            pack_type=plans[0].pack_type,
            source_pdf_path=source_pdf_path,
            source_page_index=int(source_page_index),
            target_pdf_path=target_pdf_path,
            target_page_index=int(target_page_index) if target_page_index is not None else None,
        )
    )
    prompts = resolve_stage_prompts(
        "index_visual_review",
        {
            "source_sheet_no": candidate["source_sheet_no"],
            "target_sheet_no": candidate.get("target_sheet_no") or "",
            "index_no": candidate["index_no"],
            "issue_kind": candidate["review_kind"],
            "issue_description": candidate["issue"].description,
        },
    )
    if project_id is not None and audit_version is not None and _index_stream_enabled():
        runner = _get_index_runner(project_id, audit_version)
        turn_result: RunnerTurnResult = await runner.run_stream(
            RunnerTurnRequest(
                agent_key="index_review_agent",
                agent_name="索引审查Agent",
                step_key="index",
                progress_hint=24,
                turn_kind="index_visual_review",
                system_prompt=resolve_stage_system_prompt_with_skills("index_visual_review", "index"),
                user_prompt=prompts["user_prompt"],
                images=list(pack.images.values()),
                temperature=0.0,
                max_tokens=1200,
                meta={
                    "source_sheet_no": candidate["source_sheet_no"],
                    "target_sheet_no": candidate.get("target_sheet_no"),
                    "index_no": candidate["index_no"],
                },
            ),
            should_cancel=lambda: is_cancel_requested(project_id),
        )
        result = turn_result.output if turn_result.status != "needs_review" else None
    else:
        runner = _get_index_runner(project_id or "__adhoc_index__", audit_version or 0)
        turn_result = await runner.run_once(
            RunnerTurnRequest(
                agent_key="index_review_agent",
                agent_name="索引审查Agent",
                step_key="index",
                progress_hint=24,
                turn_kind="index_visual_review",
                system_prompt=resolve_stage_system_prompt_with_skills("index_visual_review", "index"),
                user_prompt=prompts["user_prompt"],
                images=list(pack.images.values()),
                temperature=0.0,
                max_tokens=1200,
                meta={
                    "source_sheet_no": candidate["source_sheet_no"],
                    "target_sheet_no": candidate.get("target_sheet_no"),
                    "index_no": candidate["index_no"],
                },
            )
        )
        result = turn_result.output if turn_result.status != "needs_review" else None
    return result if isinstance(result, dict) else None


async def _review_index_issue_candidates_async(
    project_id: str,
    db,
    candidates: List[Dict[str, Any]],
    *,
    audit_version: int | None = None,
    skill_profile: Dict[str, Any],
    feedback_profile: Dict[str, Any],
) -> List[Dict[str, Any]]:
    if not candidates:
        return []

    if audit_version is not None:
        append_run_event(
            project_id,
            audit_version,
            level="info",
            step_key="index",
            agent_key="index_review_agent",
            agent_name="索引审查Agent",
            event_kind="phase_progress",
            progress_hint=24,
            message=f"索引审查Agent 发现 {len(candidates)} 条高歧义索引，正在做 AI 复核",
            meta={"review_candidates": len(candidates)},
        )

    asset_map = _collect_page_asset_map(
        db.query(Drawing).filter(Drawing.project_id == project_id).all()
    )
    policy = _resolve_index_review_policy(
        skill_profile=skill_profile,
        feedback_profile=feedback_profile,
    )
    kept: List[Dict[str, Any]] = []
    filtered_count = 0
    for candidate in candidates:
        try:
            result = await _run_index_ai_review(
                candidate,
                project_id=project_id,
                audit_version=audit_version,
                asset_map=asset_map,
                skill_profile=skill_profile,
            )
        except AuditCancellationRequested:
            raise
        except Exception:
            kept.append(candidate)
            continue

        if not result:
            kept.append(candidate)
            continue

        decision = str(result.get("decision") or "").strip().lower()
        try:
            confidence = float(result.get("confidence"))
        except (TypeError, ValueError):
            confidence = 0.0

        if decision == "reject" and confidence >= float(policy["confidence_floor"]):
            filtered_count += 1
            continue

        severity_override = str(
            result.get("severity_override") or policy.get("severity_override") or ""
        ).strip().lower()
        if severity_override in {"warning", "error", "info"}:
            candidate["issue"].severity = severity_override
        candidate["review_round"] = 2
        candidate["triggered_by"] = "confidence_low"
        candidate["review_confidence"] = confidence
        candidate["evidence_pack_id"] = "overview_pack"
        _merge_index_ai_review(candidate["issue"], result)
        kept.append(candidate)

    if audit_version is not None:
        append_run_event(
            project_id,
            audit_version,
            level="success",
            step_key="index",
            agent_key="index_review_agent",
            agent_name="索引审查Agent",
            event_kind="phase_progress",
            progress_hint=25,
            message=f"索引审查Agent 已完成 AI 复核，保留 {len(kept)} 条问题，排除了 {filtered_count} 条疑似误报",
            meta={
                "review_candidates": len(candidates),
                "kept": len(kept),
                "filtered": filtered_count,
            },
        )
    return kept


def _review_index_issue_candidates(
    project_id: str,
    db,
    candidates: List[Dict[str, Any]],
    *,
    audit_version: int | None = None,
    skill_profile: Dict[str, Any],
    feedback_profile: Dict[str, Any],
) -> List[Dict[str, Any]]:
    return _run_async(
        _review_index_issue_candidates_async(
            project_id,
            db,
            candidates,
            audit_version=audit_version,
            skill_profile=skill_profile,
            feedback_profile=feedback_profile,
        )
    )


def _build_sheet_validator(catalog_sheet_nos: List[str]) -> Callable[[str], bool]:
    """从目录图号列表中学习当前项目的图号命名规律，返回一个校验函数。

    校验函数返回 True 表示 target 看起来像本项目的图号；
    返回 False 表示 target 更像分图号/假阳性，应跳过。
    """
    valid_nos = [s.strip() for s in catalog_sheet_nos if s and s.strip()]
    if not valid_nos:
        return lambda _: True  # 没有目录信息，保守起见全部放行

    # 学习最短图号长度（容错 -2，允许略短的缩写写法）
    min_len = max(2, min(len(s) for s in valid_nos) - 2)

    # 学习是否需要分隔符（- . _）：70% 以上有分隔符则认为本项目图号带分隔符
    with_sep = sum(1 for s in valid_nos if re.search(r"[-._]", s))
    separator_required = with_sep >= len(valid_nos) * 0.7

    # 学习常见起始字母前缀（如 A、T、FP、PL 等）
    prefix_re = re.compile(r"^([A-Za-z]{1,4})")
    prefixes: set[str] = set()
    for s in valid_nos:
        m = prefix_re.match(s)
        if m:
            prefixes.add(m.group(1).upper())

    def validator(target: str) -> bool:
        t = (target or "").strip()
        if not t:
            return False
        # 比最短图号还短很多 → 几乎不可能是图号
        if len(t) < min_len:
            return False
        # 项目图号普遍带分隔符，但 target 没有 → 分图号假阳性
        if separator_required and not re.search(r"[-._]", t):
            return False
        # 项目有明确字母前缀，但 target 全是数字 → 不符合项目图号格式
        if prefixes and not re.match(r"[A-Za-z]", t) and re.fullmatch(r"\d+", t):
            return False
        return True

    return validator


# 功能说明：从属性列表中按标签键提取值
def _pick_attr_value(attrs: list[dict[str, Any]], keys: tuple[str, ...]) -> str:
    key_set = {key.upper() for key in keys}
    for attr in attrs:
        tag = str(attr.get("tag") or "").strip().upper()
        if tag in key_set:
            return str(attr.get("value") or "").strip()
    return ""


def _collect_target_reference_labels(
    data: Dict[str, Any],
    alias_map: Dict[str, str],
) -> set[str]:
    labels: set[str] = set()

    for idx in data.get("indexes", []) or []:
        label_key = canonicalize_index_key(str(idx.get("index_no") or "").strip(), alias_map)
        if label_key:
            labels.add(label_key)

    for title in data.get("title_blocks", []) or []:
        attrs = title.get("attrs") or []
        raw_label = (
            str(title.get("title_label") or "").strip()
            or _pick_attr_value(attrs, ("_ACM-TITLELABEL", "TITLELABEL", "TITLE_LABEL"))
        )
        label_key = canonicalize_index_key(raw_label, alias_map)
        if label_key:
            labels.add(label_key)

    for detail in data.get("detail_titles", []) or []:
        label_key = canonicalize_index_key(str(detail.get("label") or "").strip(), alias_map)
        if label_key:
            labels.add(label_key)

    return labels


# 功能说明：创建索引审核结果对象
def _issue_index(
    project_id: str,
    audit_version: int,
    severity: str,
    sheet_no_a: Optional[str],
    sheet_no_b: Optional[str],
    location: str,
    description: str,
    evidence_json: Optional[str] = None,
) -> AuditResult:
    return AuditResult(
        project_id=project_id,
        audit_version=audit_version,
        type="index",
        severity=severity,
        sheet_no_a=sheet_no_a,
        sheet_no_b=sheet_no_b,
        location=location,
        description=description,
        evidence_json=evidence_json,
    )


# 功能说明：执行图纸索引关系审核，检查索引指向的有效性和一致性
def audit_indexes(
    project_id: str,
    audit_version: int,
    db,
    source_sheet_filters: Optional[List[str]] = None,
    hot_sheet_registry: HotSheetRegistry | None = None,
) -> List[AuditResult]:
    alias_map = build_index_alias_map(load_active_skill_rules(db, skill_type="index"))
    skill_profile = load_runtime_skill_profile(
        db,
        skill_type="index",
        stage_key="index_visual_review",
    )
    feedback_profile = load_feedback_runtime_profile(db, issue_type="index")

    # 从目录中学习本项目的图号命名规律，用于过滤分图号假阳性
    catalog_sheet_nos = [
        c.sheet_no
        for c in db.query(Catalog).filter(
            Catalog.project_id == project_id,
            Catalog.status == "locked",
            Catalog.sheet_no.isnot(None),
        ).all()
        if c.sheet_no
    ]
    is_plausible_sheet = _build_sheet_validator(catalog_sheet_nos)

    allowed_source_keys: Optional[set[str]] = None
    if source_sheet_filters:
        allowed_source_keys = {
            canonicalize_sheet_key(item, alias_map)
            for item in source_sheet_filters
            if canonicalize_sheet_key(item, alias_map)
        }
        if not allowed_source_keys:
            return []

    json_list = (
        db.query(JsonData)
        .filter(
            JsonData.project_id == project_id,
            JsonData.is_latest == 1,
        )
        .all()
    )

    sheet_map: Dict[str, str] = {}
    sheet_index_defs: Dict[str, set[str]] = defaultdict(set)
    sheet_detail_label_defs: Dict[str, set[str]] = defaultdict(set)
    forward_links: List[Dict[str, Any]] = []
    orphan_candidates: List[Dict[str, Any]] = []
    sheet_index_anchor_map: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)

    for json_data in json_list:
        json_path = json_data.json_path or ""
        if not json_path:
            continue

        data = load_enriched_layout_json(json_path)
        if not data:
            continue

        raw_sheet_no = (json_data.sheet_no or data.get("sheet_no") or "").strip()
        if not raw_sheet_no:
            continue
        src_key = canonicalize_sheet_key(raw_sheet_no, alias_map)
        if not src_key:
            continue
        sheet_map.setdefault(src_key, raw_sheet_no)

        indexes = data.get("indexes", []) or []
        for idx in indexes:
            raw_index_no = str(idx.get("index_no", "") or "").strip()
            raw_target_sheet = str(idx.get("target_sheet", "") or "").strip()
            idx_key = canonicalize_index_key(raw_index_no, alias_map)
            tgt_key = canonicalize_sheet_key(raw_target_sheet, alias_map)
            source_anchor = build_anchor(
                role="source",
                sheet_no=raw_sheet_no,
                grid=str(idx.get("grid") or "").strip(),
                global_pct=idx.get("global_pct") if isinstance(idx.get("global_pct"), dict) else None,
                confidence=1.0,
                origin="index",
            )

            if idx_key:
                sheet_index_defs[src_key].add(idx_key)
                if source_anchor and idx_key not in sheet_index_anchor_map[src_key]:
                    sheet_index_anchor_map[src_key][idx_key] = source_anchor

            # 本图索引（下方为短横线）：不涉及跨图验证，直接跳过
            if idx.get("same_sheet"):
                continue

            if not idx_key and not tgt_key:
                continue

            # 用目录学到的图号格式校验 target_sheet：
            # 若 target 不像本项目的图号（如分图号 "A"、"01"），直接丢弃，不报错
            if raw_target_sheet and not is_plausible_sheet(raw_target_sheet):
                continue

            row = {
                "source_raw": raw_sheet_no,
                "source_key": src_key,
                "index_raw": raw_index_no,
                "index_key": idx_key,
                "target_raw": raw_target_sheet,
                "target_key": tgt_key,
                "source_anchor": source_anchor,
            }
            if tgt_key:
                forward_links.append(row)
            elif idx_key:
                orphan_candidates.append(row)

        sheet_detail_label_defs[src_key].update(_collect_target_reference_labels(data, alias_map))

    issue_candidates: List[Dict[str, Any]] = []
    existing_sheets = set(sheet_map.keys())
    referenced_targets = {
        (item["target_key"], item["index_key"])
        for item in forward_links
        if item["target_key"] and item["index_key"]
    }
    reverse_link_keys = {
        (item["source_key"], item["target_key"])
        for item in forward_links
        if item["source_key"] and item["target_key"]
    }

    for rel in forward_links:
        if allowed_source_keys is not None and rel["source_key"] not in allowed_source_keys:
            continue
        tgt_key = rel["target_key"]
        if tgt_key not in existing_sheets:
            anchors = [rel["source_anchor"]] if rel.get("source_anchor") else []
            issue = _issue_index(
                project_id=project_id,
                audit_version=audit_version,
                severity="error",
                sheet_no_a=rel["source_raw"],
                sheet_no_b=rel["target_raw"] or None,
                location=f"索引{rel['index_raw'] or '?'}",
                description=(
                    f"图纸{rel['source_raw']}中的索引{rel['index_raw'] or '?'}"
                    f" 指向 {rel['target_raw'] or '未知图号'}，但目录/数据中不存在该目标图。"
                ),
                evidence_json=to_evidence_json(
                    anchors, unlocated_reason=None if anchors else "missing_target_sheet"
                ),
            )
            issue_candidates.append(
                {
                    "issue": issue,
                    "review_kind": "missing_target_sheet",
                    "source_sheet_no": rel["source_raw"],
                    "target_sheet_no": rel["target_raw"] or None,
                    "source_key": rel["source_key"],
                    "target_key": rel["target_key"],
                    "index_no": rel["index_raw"] or "?",
                }
            )

    for rel in forward_links:
        if allowed_source_keys is not None and rel["source_key"] not in allowed_source_keys:
            continue
        tgt_key = rel["target_key"]
        idx_key = rel["index_key"]
        if not tgt_key or tgt_key not in existing_sheets or not idx_key:
            continue
        target_index_defs = sheet_index_defs.get(tgt_key, set())
        target_detail_labels = sheet_detail_label_defs.get(tgt_key, set())
        if idx_key not in target_index_defs and idx_key not in target_detail_labels:
            target_raw = sheet_map.get(tgt_key, rel["target_raw"] or "")
            anchors = [rel["source_anchor"]] if rel.get("source_anchor") else []
            issue = _issue_index(
                project_id=project_id,
                audit_version=audit_version,
                severity="error",
                sheet_no_a=rel["source_raw"],
                sheet_no_b=target_raw or rel["target_raw"] or None,
                location=f"索引{rel['index_raw'] or '?'}",
                description=(
                    f"图纸{rel['source_raw']}中的索引{rel['index_raw'] or '?'} 指向 {target_raw or rel['target_raw'] or '目标图'}，"
                    "但目标图中未找到同编号索引。"
                ),
                evidence_json=to_evidence_json(
                    anchors, unlocated_reason=None if anchors else "missing_target_index_no"
                ),
            )
            issue_candidates.append(
                {
                    "issue": issue,
                    "review_kind": "missing_target_index_no",
                    "source_sheet_no": rel["source_raw"],
                    "target_sheet_no": target_raw or rel["target_raw"] or None,
                    "source_key": rel["source_key"],
                    "target_key": rel["target_key"],
                    "index_no": rel["index_raw"] or "?",
                }
            )

    for rel in forward_links:
        if allowed_source_keys is not None and rel["source_key"] not in allowed_source_keys:
            continue
        src_key = rel["source_key"]
        tgt_key = rel["target_key"]
        if not src_key or not tgt_key or src_key == tgt_key or tgt_key not in existing_sheets:
            continue
        target_index_defs = sheet_index_defs.get(tgt_key, set())
        target_detail_labels = sheet_detail_label_defs.get(tgt_key, set())
        if rel["index_key"] and rel["index_key"] in target_detail_labels:
            continue
        if rel["index_key"] and rel["index_key"] not in target_index_defs and rel["index_key"] not in target_detail_labels:
            continue
        if (tgt_key, src_key) in reverse_link_keys:
            continue
        target_raw = sheet_map.get(tgt_key, rel["target_raw"] or "")
        anchors: List[Dict[str, Any]] = []
        if rel.get("source_anchor"):
            anchors.append(rel["source_anchor"])
        target_anchor = sheet_index_anchor_map.get(tgt_key, {}).get(rel["index_key"] or "")
        if target_anchor:
            target_anchor = dict(target_anchor)
            target_anchor["role"] = "target"
            anchors.append(target_anchor)
        issue = _issue_index(
            project_id=project_id,
            audit_version=audit_version,
            severity="warning",
            sheet_no_a=rel["source_raw"],
            sheet_no_b=target_raw or rel["target_raw"] or None,
            location=f"索引{rel['index_raw'] or '?'}",
            description=(
                f"图纸{rel['source_raw']}指向{target_raw or rel['target_raw'] or '目标图'}，"
                f"但未发现{target_raw or rel['target_raw'] or '目标图'}反向指向{rel['source_raw']}，请确认索引链闭合性。"
            ),
            evidence_json=to_evidence_json(
                anchors, unlocated_reason=None if anchors else "missing_reverse_link"
            ),
        )
        issue_candidates.append(
            {
                "issue": issue,
                "review_kind": "missing_reverse_link",
                "source_sheet_no": rel["source_raw"],
                "target_sheet_no": target_raw or rel["target_raw"] or None,
                "source_key": rel["source_key"],
                "target_key": rel["target_key"],
                "index_no": rel["index_raw"] or "?",
            }
        )

    for orphan in orphan_candidates:
        if allowed_source_keys is not None and orphan["source_key"] not in allowed_source_keys:
            continue
        pair = (orphan["source_key"], orphan["index_key"])
        if pair in referenced_targets:
            continue
        anchors = [orphan["source_anchor"]] if orphan.get("source_anchor") else []
        issue = _issue_index(
            project_id=project_id,
            audit_version=audit_version,
            severity="warning",
            sheet_no_a=orphan["source_raw"],
            sheet_no_b=None,
            location=f"索引{orphan['index_raw'] or '?'}",
            description=(
                f"图纸{orphan['source_raw']}中的索引{orphan['index_raw'] or '?'} 未标注目标图号，且未被其他图纸引用，可能是孤立索引。"
            ),
            evidence_json=to_evidence_json(
                anchors, unlocated_reason=None if anchors else "orphan_index_without_target"
            ),
        )
        issue_candidates.append(
            {
                "issue": issue,
                "review_kind": "orphan_index_without_target",
                "source_sheet_no": orphan["source_raw"],
                "target_sheet_no": None,
                "source_key": orphan["source_key"],
                "target_key": "",
                "index_no": orphan["index_raw"] or "?",
            }
        )

    reviewable_candidates = [
        candidate
        for candidate in issue_candidates
        if _reviewable_index_issue(candidate["review_kind"])
    ]
    final_candidates = [
        candidate
        for candidate in issue_candidates
        if not _reviewable_index_issue(candidate["review_kind"])
    ]

    if _index_ai_review_enabled():
        final_candidates.extend(
            _review_index_issue_candidates(
                project_id,
                db,
                reviewable_candidates,
                audit_version=audit_version,
                skill_profile=skill_profile,
                feedback_profile=feedback_profile,
            )
        )
    else:
        final_candidates.extend(reviewable_candidates)

    issues: List[AuditResult] = []
    for candidate in final_candidates:
        issue = _apply_index_finding(candidate["issue"], candidate)
        db.add(issue)
        db.flush()
        ensure_issue_drawing_matches(issue, db)
        issues.append(issue)
        if hot_sheet_registry is not None:
            confidence = float(getattr(issue, "confidence", None) or (0.85 if issue.severity == "error" else 0.65))
            hot_sheet_registry.publish(
                issue.sheet_no_a,
                finding_type=candidate.get("review_kind") or "index_review",
                confidence=confidence,
                source_agent="index_review_agent",
            )
            hot_sheet_registry.publish(
                issue.sheet_no_b,
                finding_type=candidate.get("review_kind") or "index_review",
                confidence=confidence,
                source_agent="index_review_agent",
            )

    db.commit()
    return issues
