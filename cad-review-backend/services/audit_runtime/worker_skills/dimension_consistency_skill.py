"""尺寸一致性副审 skill。"""

from __future__ import annotations

from typing import Any

from domain.sheet_normalization import normalize_sheet_no
from services.audit.dimension_audit import _collect_dimension_pair_issues_async, _dimension_issue_evidence
from services.audit.prompt_builder import build_pair_compare_prompt
from services.audit_runtime.contracts import EvidencePackType, EvidenceRequest
from services.audit_runtime.cross_sheet_index import build_cross_sheet_index
from services.audit_runtime.cross_sheet_locator import locate_across_sheets
from services.audit_runtime.evidence_prefetch_service import prefetch_regions
from services.audit_runtime.runtime_prompt_assembler import assemble_worker_runtime_prompt
from services.audit_runtime.worker_skill_contract import (
    build_task_event_meta,
    build_worker_skill_result,
    extract_anchors_from_issue_results,
)
from services.audit_runtime.worker_skill_loader import WorkerSkillBundle, load_worker_skill


def _extract_sheet_assets(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets_by_sheet: dict[str, dict[str, Any]] = {}
    for raw_assets in (context.get("sheet_assets"), context.get("page_assets_by_sheet")):
        if isinstance(raw_assets, dict):
            items = raw_assets.items()
        elif isinstance(raw_assets, list):
            items = [(None, item) for item in raw_assets]
        else:
            continue
        for raw_key, raw_value in items:
            if not isinstance(raw_value, dict):
                continue
            canonical_sheet_no = str(raw_value.get("sheet_no") or raw_key or "").strip()
            sheet_key = normalize_sheet_no(canonical_sheet_no)
            if not sheet_key:
                continue
            pdf_path = str(raw_value.get("pdf_path") or "").strip()
            page_index = raw_value.get("page_index")
            if not pdf_path or not isinstance(page_index, int):
                continue
            assets_by_sheet[sheet_key] = {
                "sheet_no": canonical_sheet_no or str(raw_key or "").strip() or sheet_key,
                "pdf_path": pdf_path,
                "page_index": int(page_index),
            }
    return assets_by_sheet


def _build_default_sheet_regions(
    *,
    sheet_assets: list[dict[str, Any]],
    label_hint: str,
) -> list[dict[str, Any]]:
    default_label = label_hint or "cross_sheet_anchor"
    return [
        {
            "sheet_no": str(asset["sheet_no"]),
            "label": default_label,
            "bbox_pct": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        }
        for asset in sheet_assets
    ]


def _extract_sheet_regions(
    *,
    context: dict[str, Any],
    asset_map: dict[str, dict[str, Any]],
    label_hint: str,
) -> list[dict[str, Any]]:
    raw_regions = context.get("cross_sheet_regions")
    if isinstance(raw_regions, list):
        regions: list[dict[str, Any]] = []
        for item in raw_regions:
            if not isinstance(item, dict):
                continue
            sheet_key = normalize_sheet_no(str(item.get("sheet_no") or "").strip())
            asset = asset_map.get(sheet_key)
            if not asset or not isinstance(item.get("bbox_pct"), dict):
                continue
            regions.append(
                {
                    "sheet_no": asset["sheet_no"],
                    "label": str(item.get("label") or label_hint or "cross_sheet_anchor").strip()
                    or "cross_sheet_anchor",
                    "bbox_pct": dict(item.get("bbox_pct") or {}),
                    "meta": dict(item.get("meta") or {}),
                }
            )
        if regions:
            return regions
    return _build_default_sheet_regions(sheet_assets=list(asset_map.values()), label_hint=label_hint)


def _build_prefetch_requests_from_pairs(
    *,
    anchor_pairs: list[Any],
    asset_map: dict[str, dict[str, Any]],
    focus_hint: str,
) -> list[EvidenceRequest]:
    requests: list[EvidenceRequest] = []
    for pair in anchor_pairs:
        source_asset = asset_map.get(normalize_sheet_no(str(pair.source_sheet_no or "").strip()))
        target_asset = asset_map.get(normalize_sheet_no(str(pair.target_sheet_no or "").strip()))
        if not source_asset or not target_asset:
            continue
        requests.append(
            EvidenceRequest(
                pack_type=EvidencePackType.PAIRED_OVERVIEW_PACK,
                source_pdf_path=source_asset["pdf_path"],
                source_page_index=int(source_asset["page_index"]),
                target_pdf_path=target_asset["pdf_path"],
                target_page_index=int(target_asset["page_index"]),
                focus_hint=focus_hint,
            )
        )
    return requests


def _build_pair_prefetch_requests(
    *,
    source_asset: dict[str, Any],
    target_assets: list[dict[str, Any]],
    focus_hint: str,
) -> list[EvidenceRequest]:
    return [
        EvidenceRequest(
            pack_type=EvidencePackType.PAIRED_OVERVIEW_PACK,
            source_pdf_path=str(source_asset["pdf_path"]),
            source_page_index=int(source_asset["page_index"]),
            target_pdf_path=str(target_asset["pdf_path"]),
            target_page_index=int(target_asset["page_index"]),
            focus_hint=focus_hint,
        )
        for target_asset in target_assets
    ]


async def _prepare_cross_sheet_prefetch(task) -> dict[str, Any]:
    asset_map = _extract_sheet_assets(dict(task.context or {}))
    source_key = normalize_sheet_no(task.source_sheet_no)
    if not source_key or source_key not in asset_map:
        return {"cross_sheet_anchor_count": 0, "prefetch_request_count": 0, "prefetch_unique_request_count": 0, "prefetch_cache_hits": 0, "cross_sheet_prefetch_status": "skipped"}

    target_assets = [
        asset_map[target_key]
        for target_key in [normalize_sheet_no(item) for item in list(task.target_sheet_nos or [])]
        if target_key and target_key in asset_map
    ]
    if not target_assets:
        return {"cross_sheet_anchor_count": 0, "prefetch_request_count": 0, "prefetch_unique_request_count": 0, "prefetch_cache_hits": 0, "cross_sheet_prefetch_status": "skipped"}

    source_asset = asset_map[source_key]
    focus_hint = str((task.anchor_hint or {}).get("label") or task.objective or "").strip()
    candidate_index = build_cross_sheet_index(
        sheet_regions=_extract_sheet_regions(
            context=dict(task.context or {}),
            asset_map={source_key: source_asset, **{normalize_sheet_no(str(item["sheet_no"])): item for item in target_assets}},
            label_hint=focus_hint,
        )
    )
    anchor_pairs = locate_across_sheets(
        source_sheet_no=str(source_asset["sheet_no"]),
        target_sheet_nos=[str(item["sheet_no"]) for item in target_assets],
        anchor_hint=dict(task.anchor_hint or {"label": focus_hint}),
        candidate_index=candidate_index,
    )
    requests = _build_prefetch_requests_from_pairs(
        anchor_pairs=anchor_pairs,
        asset_map=asset_map,
        focus_hint=focus_hint,
    )
    if not requests:
        requests = _build_pair_prefetch_requests(
            source_asset=source_asset,
            target_assets=target_assets,
            focus_hint=focus_hint,
        )
    if not requests:
        return {"cross_sheet_anchor_count": len(anchor_pairs), "prefetch_request_count": 0, "prefetch_unique_request_count": 0, "prefetch_cache_hits": 0, "cross_sheet_prefetch_status": "skipped"}

    batch = await prefetch_regions(requests=requests)
    return {
        "cross_sheet_anchor_count": len(anchor_pairs),
        "prefetch_request_count": batch.total_request_count,
        "prefetch_unique_request_count": batch.unique_request_count,
        "prefetch_cache_hits": batch.cache_hits,
        "cross_sheet_prefetch_status": "ready",
    }


def _build_sheet_prompt_bundle(
    worker_kind: str,
    job: dict,
    stage_key: str,
    event_meta: dict[str, Any] | None = None,
):
    analysis_mode = {
        "dimension_single_sheet": "single_sheet_semantic",
        "dimension_visual_only": "visual_grounding",
    }.get(stage_key, "single_sheet_semantic")
    return assemble_worker_runtime_prompt(
        worker_kind=worker_kind,
        task_context={
            "analysis_mode": analysis_mode,
            "sheet_no": job["sheet_no"],
            "sheet_name": job.get("sheet_name") or "",
            "visual_only": bool(job.get("visual_only")),
        },
        extra_meta=event_meta,
        user_prompt_override=job["prompt"],
    )


def _build_pair_prompt_bundle(
    worker_kind: str,
    job: dict,
    event_meta: dict[str, Any] | None = None,
):
    return assemble_worker_runtime_prompt(
        worker_kind=worker_kind,
        task_context={
            "analysis_mode": "cross_sheet_compare",
            "source_sheet_no": job["a_sheet_no"],
            "target_sheet_no": job["b_sheet_no"],
            "source_sheet_name": job["a_sheet_name"],
            "target_sheet_name": job["b_sheet_name"],
        },
        extra_meta=event_meta,
        user_prompt_override=build_pair_compare_prompt(
            a_sheet_no=job["a_sheet_no"],
            a_sheet_name=job["a_sheet_name"],
            a_semantic=job["semantic_a"],
            b_sheet_no=job["b_sheet_no"],
            b_sheet_name=job["b_sheet_name"],
            b_semantic=job["semantic_b"],
        ),
    )


async def run_dimension_consistency_skill(
    *,
    task,
    db,
    skill_bundle: WorkerSkillBundle | None = None,
):
    skill = skill_bundle or load_worker_skill(str(task.worker_kind or "").strip())
    task_context = dict(task.context or {})
    event_meta = build_task_event_meta(task)
    project_id = str(task_context.get("project_id") or "").strip()
    audit_version = int(task_context.get("audit_version") or 0)
    prefetch_meta = {
        "cross_sheet_anchor_count": 0,
        "prefetch_request_count": 0,
        "prefetch_unique_request_count": 0,
        "prefetch_cache_hits": 0,
        "cross_sheet_prefetch_status": "skipped",
    }
    try:
        prefetch_meta = await _prepare_cross_sheet_prefetch(task)
    except Exception:
        prefetch_meta = {**prefetch_meta, "cross_sheet_prefetch_status": "failed"}
    pair_filters = [
        (task.source_sheet_no, target_sheet_no)
        for target_sheet_no in list(task.target_sheet_nos or [])
        if str(target_sheet_no or "").strip()
    ]
    issues = await _collect_dimension_pair_issues_async(
        project_id,
        audit_version,
        db,
        pair_filters=pair_filters or None,
        sheet_prompt_bundle_builder=lambda job, stage_key: _build_sheet_prompt_bundle(
            skill.worker_kind,
            job,
            stage_key,
            event_meta,
        ),
        pair_prompt_bundle_builder=lambda job: _build_pair_prompt_bundle(
            skill.worker_kind,
            job,
            event_meta,
        ),
    )
    if not issues:
        return build_worker_skill_result(
            task=task,
            skill_bundle=skill,
            status="rejected",
            confidence=0.72,
            summary=f"原生尺寸副审未发现 {task.source_sheet_no} 与目标图之间的尺寸问题",
            rule_id="dimension_pair_compare",
            evidence_pack_id="paired_overview_pack",
            meta={"prompt_source": "agent_skill", "issue_count": 0, **prefetch_meta},
        )

    evidence = [_dimension_issue_evidence(issue) for issue in issues[:5]]
    first = evidence[0]
    status = "confirmed"
    if any(str(issue.finding_status or "").strip().lower() == "needs_review" for issue in issues):
        status = "needs_review"
    confidence_values = [
        float(issue.confidence)
        for issue in issues
        if isinstance(issue.confidence, (int, float))
    ]
    confidence = max(confidence_values) if confidence_values else 0.84
    return build_worker_skill_result(
        task=task,
        skill_bundle=skill,
        status=status,
        confidence=confidence,
        summary=str(issues[0].description or f"原生尺寸副审返回 {len(issues)} 处尺寸问题").strip(),
        rule_id=str(first["rule_id"]),
        evidence_pack_id=str(first["evidence_pack_id"]),
        evidence=evidence,
        anchors=extract_anchors_from_issue_results(issues),
        raw_skill_outputs=[
            {
                "sheet_no_a": str(issue.sheet_no_a or ""),
                "sheet_no_b": str(issue.sheet_no_b or ""),
                "description": str(issue.description or "").strip(),
            }
            for issue in issues[:5]
        ],
        escalate_to_chief=(status == "needs_review"),
        meta={
            "prompt_source": "agent_skill",
            "sheet_no": first["sheet_no"],
            "location": first["location"],
            "severity": first["severity"],
            "issue_count": len(issues),
            "review_round": max(int(issue.review_round or 1) for issue in issues),
            **prefetch_meta,
        },
    )


__all__ = ["run_dimension_consistency_skill"]
