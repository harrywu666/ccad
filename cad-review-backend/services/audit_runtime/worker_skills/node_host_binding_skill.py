"""节点归属副审 skill。"""

from __future__ import annotations

from typing import Any

from domain.sheet_normalization import normalize_sheet_no
from services.audit.relationship_discovery import (
    _build_relationship_task_prompt,
    _discover_relationship_task_v2,
    _load_ready_sheets,
    _validate_and_normalize,
    attach_relationship_findings,
    get_evidence_service,
)
from services.audit_runtime.contracts import EvidencePackType, EvidenceRequest
from services.audit_runtime.cross_sheet_index import build_cross_sheet_index
from services.audit_runtime.cross_sheet_locator import locate_across_sheets
from services.audit_runtime.evidence_prefetch_service import prefetch_regions
from services.audit_runtime.runtime_prompt_assembler import assemble_worker_runtime_prompt
from services.audit_runtime.worker_skill_contract import build_task_event_meta, build_worker_skill_result
from services.audit_runtime.worker_skill_loader import WorkerSkillBundle, load_worker_skill
from services.feedback_runtime_service import load_feedback_runtime_profile
from services.skill_pack_service import load_runtime_skill_profile
from services.ai_service import call_kimi


def _build_sheet_regions(
    *,
    sheets: list[dict[str, Any]],
    task,
) -> list[dict[str, Any]]:
    sheet_map = {
        normalize_sheet_no(str(item.get("sheet_no") or "").strip()): item
        for item in sheets
        if normalize_sheet_no(str(item.get("sheet_no") or "").strip())
    }
    raw_regions = task.context.get("cross_sheet_regions") if isinstance(task.context, dict) else None
    if isinstance(raw_regions, list):
        regions: list[dict[str, Any]] = []
        for item in raw_regions:
            if not isinstance(item, dict):
                continue
            sheet_key = normalize_sheet_no(str(item.get("sheet_no") or "").strip())
            sheet = sheet_map.get(sheet_key)
            if not sheet or not isinstance(item.get("bbox_pct"), dict):
                continue
            regions.append(
                {
                    "sheet_no": str(sheet["sheet_no"]),
                    "label": str(item.get("label") or task.objective or "cross_sheet_anchor").strip()
                    or "cross_sheet_anchor",
                    "bbox_pct": dict(item.get("bbox_pct") or {}),
                    "meta": dict(item.get("meta") or {}),
                }
            )
        if regions:
            return regions
    label_hint = str((task.anchor_hint or {}).get("label") or task.objective or "cross_sheet_anchor").strip()
    return [
        {
            "sheet_no": str(sheet["sheet_no"]),
            "label": label_hint or "cross_sheet_anchor",
            "bbox_pct": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        }
        for sheet in sheets
    ]


async def _prepare_cross_sheet_prefetch(
    *,
    task,
    source_sheet: dict[str, Any],
    target_sheets: list[dict[str, Any]],
    evidence_service,
) -> dict[str, Any]:
    focus_hint = str((task.anchor_hint or {}).get("label") or task.objective or "").strip()
    candidate_index = build_cross_sheet_index(
        sheet_regions=_build_sheet_regions(sheets=[source_sheet, *target_sheets], task=task)
    )
    anchor_pairs = locate_across_sheets(
        source_sheet_no=str(source_sheet["sheet_no"]),
        target_sheet_nos=[str(item["sheet_no"]) for item in target_sheets],
        anchor_hint=dict(task.anchor_hint or {"label": focus_hint}),
        candidate_index=candidate_index,
    )
    requests = [
        EvidenceRequest(
            pack_type=EvidencePackType.PAIRED_OVERVIEW_PACK,
            source_pdf_path=str(source_sheet["pdf_path"]),
            source_page_index=int(source_sheet["page_index"]),
            target_pdf_path=str(target_sheet["pdf_path"]),
            target_page_index=int(target_sheet["page_index"]),
            focus_hint=focus_hint,
        )
        for target_sheet in target_sheets
        if str(target_sheet.get("pdf_path") or "").strip()
    ]
    if not requests:
        return {
            "cross_sheet_anchor_count": len(anchor_pairs),
            "prefetch_request_count": 0,
            "prefetch_unique_request_count": 0,
            "prefetch_cache_hits": 0,
            "cross_sheet_prefetch_status": "skipped",
        }
    batch = await prefetch_regions(
        requests=requests,
        evidence_service=evidence_service,
    )
    return {
        "cross_sheet_anchor_count": len(anchor_pairs),
        "prefetch_request_count": batch.total_request_count,
        "prefetch_unique_request_count": batch.unique_request_count,
        "prefetch_cache_hits": batch.cache_hits,
        "cross_sheet_prefetch_status": "ready",
    }


async def run_node_host_binding_skill(
    *,
    task,
    db,
    skill_bundle: WorkerSkillBundle | None = None,
):
    skill = skill_bundle or load_worker_skill("node_host_binding")
    event_meta = build_task_event_meta(task)
    project_id = str(task.context.get("project_id") or "").strip()
    audit_version = int(task.context.get("audit_version") or 0)
    sheet_filters = [task.source_sheet_no, *list(task.target_sheet_nos or [])]
    sheets = _load_ready_sheets(project_id, db, sheet_filters=sheet_filters)
    if not sheets:
        return build_worker_skill_result(
            task=task,
            skill_bundle=skill,
            status="rejected",
            confidence=0.4,
            summary=f"原生节点归属副审未找到可用图纸：{task.source_sheet_no}",
            rule_id="relationship_visual_review",
            evidence_pack_id="paired_overview_pack",
            meta={"prompt_source": "agent_skill", "issue_count": 0},
        )

    sheet_map = {
        normalize_sheet_no(str(item.get("sheet_no") or "")): item
        for item in sheets
        if normalize_sheet_no(str(item.get("sheet_no") or ""))
    }
    source_sheet = sheet_map.get(normalize_sheet_no(task.source_sheet_no))
    if not source_sheet:
        return build_worker_skill_result(
            task=task,
            skill_bundle=skill,
            status="rejected",
            confidence=0.4,
            summary=f"原生节点归属副审缺少源图：{task.source_sheet_no}",
            rule_id="relationship_visual_review",
            evidence_pack_id="paired_overview_pack",
            meta={"prompt_source": "agent_skill", "issue_count": 0},
        )

    target_sheets = [
        sheet_map[target_key]
        for target_key in [normalize_sheet_no(item) for item in task.target_sheet_nos]
        if target_key and target_key in sheet_map
    ]
    if not target_sheets:
        return build_worker_skill_result(
            task=task,
            skill_bundle=skill,
            status="rejected",
            confidence=0.4,
            summary=f"原生节点归属副审缺少目标图：{task.source_sheet_no}",
            rule_id="relationship_visual_review",
            evidence_pack_id="paired_overview_pack",
            meta={"prompt_source": "agent_skill", "issue_count": 0},
        )

    skill_profile = load_runtime_skill_profile(
        db,
        skill_type="index",
    )
    feedback_profile = load_feedback_runtime_profile(db, issue_type="index")
    evidence_service = get_evidence_service()
    prefetch_meta = {
        "cross_sheet_anchor_count": 0,
        "prefetch_request_count": 0,
        "prefetch_unique_request_count": 0,
        "prefetch_cache_hits": 0,
        "cross_sheet_prefetch_status": "skipped",
    }
    try:
        prefetch_meta = await _prepare_cross_sheet_prefetch(
            task=task,
            source_sheet=source_sheet,
            target_sheets=target_sheets,
            evidence_service=evidence_service,
        )
    except Exception:
        prefetch_meta = {**prefetch_meta, "cross_sheet_prefetch_status": "failed"}

    raw_relationships: list[dict[str, Any]] = []
    for target_sheet in target_sheets:
        raw_relationships.extend(
            await _discover_relationship_task_v2(
                source_sheet=source_sheet,
                target_sheet=target_sheet,
                call_kimi=call_kimi,
                project_id=project_id,
                audit_version=audit_version or None,
                evidence_service=evidence_service,
                skill_profile=skill_profile,
                feedback_profile=feedback_profile,
                hot_sheet_registry=None,
                prompt_bundle=assemble_worker_runtime_prompt(
                    worker_kind="node_host_binding",
                    task_context={
                        "source_sheet_no": source_sheet["sheet_no"],
                        "target_sheet_no": target_sheet["sheet_no"],
                        "objective": task.objective,
                    },
                    extra_meta=event_meta,
                    user_prompt_override=_build_relationship_task_prompt(source_sheet, target_sheet),
                ),
            )
        )

    valid_sheet_nos = {
        normalize_sheet_no(str(item.get("sheet_no") or ""))
        for item in sheets
        if normalize_sheet_no(str(item.get("sheet_no") or ""))
    }
    relationships = _validate_and_normalize(raw_relationships, valid_sheet_nos)
    if not all(isinstance(item.get("finding"), dict) for item in relationships):
        relationships = attach_relationship_findings(relationships, review_round=1)

    if not relationships:
        return build_worker_skill_result(
            task=task,
            skill_bundle=skill,
            status="rejected",
            confidence=0.71,
            summary=f"原生节点归属副审未发现 {task.source_sheet_no} 与目标图之间的明确挂接问题",
            rule_id="relationship_visual_review",
            evidence_pack_id="paired_overview_pack",
            result_kind="non_issue",
            meta={"prompt_source": "agent_skill", "issue_count": 0, **prefetch_meta},
        )

    evidence: list[dict[str, Any]] = []
    anchors: list[dict[str, Any]] = []
    confidence = 0.81
    for item in relationships[:5]:
        finding = dict(item.get("finding") or {})
        confidence = max(confidence, float(item.get("confidence") or finding.get("confidence") or 0.81))
        for anchor_key in ("source_anchor", "target_anchor"):
            anchor = item.get(anchor_key)
            if isinstance(anchor, dict):
                anchors.append(dict(anchor))
        evidence.append(
            {
                "sheet_no": str(finding.get("sheet_no") or item.get("source") or task.source_sheet_no or "UNKNOWN").strip()
                or "UNKNOWN",
                "location": str(finding.get("location") or f"{item.get('source')} -> {item.get('target')}").strip()
                or "未定位",
                "rule_id": str(finding.get("rule_id") or "relationship_visual_review").strip()
                or "relationship_visual_review",
                "evidence_pack_id": str(
                    finding.get("evidence_pack_id") or item.get("evidence_pack_id") or "paired_overview_pack"
                ).strip()
                or "paired_overview_pack",
                "description": str(finding.get("description") or item.get("visual_evidence") or "").strip(),
                "severity": str(finding.get("severity") or "warning").strip().lower() or "warning",
            }
        )
    first = evidence[0]
    return build_worker_skill_result(
        task=task,
        skill_bundle=skill,
        status="confirmed",
        confidence=confidence,
        summary=first["description"] or f"原生节点归属副审返回 {len(relationships)} 处跨图挂接问题",
        rule_id=str(first["rule_id"]),
        evidence_pack_id=str(first["evidence_pack_id"]),
        result_kind="relationship_signal",
        evidence=evidence,
        anchors=anchors,
        raw_skill_outputs=[
            {
                "source": str(item.get("source") or ""),
                "target": str(item.get("target") or ""),
                "description": str((item.get("finding") or {}).get("description") or item.get("visual_evidence") or "").strip(),
            }
            for item in relationships[:5]
        ],
        meta={
            "prompt_source": "agent_skill",
            "sheet_no": first["sheet_no"],
            "location": first["location"],
            "severity": first["severity"],
            "issue_count": len(relationships),
            "review_round": 1,
            **prefetch_meta,
        },
    )


__all__ = ["run_node_host_binding_skill"]
