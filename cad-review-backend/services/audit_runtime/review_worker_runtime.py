"""原生副审执行入口。"""

from __future__ import annotations

import json
from typing import Any

from domain.sheet_normalization import normalize_sheet_no
from services.audit_runtime.review_task_schema import WorkerResultCard, WorkerTaskCard
from services.feedback_runtime_service import load_feedback_runtime_profile
from services.kimi_service import call_kimi
from services.skill_pack_service import load_runtime_skill_profile


async def run_native_review_worker(
    *,
    task: WorkerTaskCard,
    db,
) -> WorkerResultCard | None:  # noqa: ANN001
    worker_kind = str(task.worker_kind or "").strip()
    if worker_kind == "node_host_binding":
        return await _run_node_host_binding_worker(task=task, db=db)
    if worker_kind == "index_reference":
        return await _run_index_reference_worker(task=task, db=db)
    if worker_kind == "material_semantic_consistency":
        return await _run_material_semantic_worker(task=task, db=db)
    if worker_kind in {"elevation_consistency", "spatial_consistency"}:
        return await _run_dimension_consistency_worker(task=task, db=db)
    return None


def _build_native_result(
    *,
    task: WorkerTaskCard,
    status: str,
    confidence: float,
    summary: str,
    rule_id: str = "relationship_visual_review",
    evidence_pack_id: str = "paired_overview_pack",
) -> WorkerResultCard:
    return WorkerResultCard(
        task_id=task.id,
        hypothesis_id=task.hypothesis_id,
        worker_kind=task.worker_kind,
        status=status,
        confidence=confidence,
        summary=summary,
        meta={
            "compat_mode": "native_worker",
            "sheet_no": task.source_sheet_no,
            "location": task.objective,
            "rule_id": rule_id,
            "evidence_pack_id": evidence_pack_id,
        },
    )


async def _run_node_host_binding_worker(
    *,
    task: WorkerTaskCard,
    db,
) -> WorkerResultCard:
    from services.audit.relationship_discovery import (
        _discover_relationship_task_v2,
        _load_ready_sheets,
        _relationship_worker_result_from_relationships,
        _validate_and_normalize,
        attach_relationship_findings,
        get_evidence_service,
    )

    project_id = str(task.context.get("project_id") or "").strip()
    audit_version = int(task.context.get("audit_version") or 0)
    sheet_filters = [task.source_sheet_no, *list(task.target_sheet_nos or [])]
    sheets = _load_ready_sheets(project_id, db, sheet_filters=sheet_filters)
    if not sheets:
        return _build_native_result(
            task=task,
            status="rejected",
            confidence=0.4,
            summary=f"原生节点归属副审未找到可用图纸：{task.source_sheet_no}",
        )

    sheet_map = {
        normalize_sheet_no(str(item.get("sheet_no") or "")): item
        for item in sheets
        if normalize_sheet_no(str(item.get("sheet_no") or ""))
    }
    source_sheet = sheet_map.get(normalize_sheet_no(task.source_sheet_no))
    if not source_sheet:
        return _build_native_result(
            task=task,
            status="rejected",
            confidence=0.4,
            summary=f"原生节点归属副审缺少源图：{task.source_sheet_no}",
        )

    target_sheets = [
        sheet_map[target_key]
        for target_key in [normalize_sheet_no(item) for item in task.target_sheet_nos]
        if target_key and target_key in sheet_map
    ]
    if not target_sheets:
        return _build_native_result(
            task=task,
            status="rejected",
            confidence=0.4,
            summary=f"原生节点归属副审缺少目标图：{task.source_sheet_no}",
        )

    skill_profile = load_runtime_skill_profile(
        db,
        skill_type="index",
        stage_key="sheet_relationship_discovery",
    )
    feedback_profile = load_feedback_runtime_profile(db, issue_type="index")
    evidence_service = get_evidence_service()

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
    result = _relationship_worker_result_from_relationships(task, relationships)
    meta = dict(result.meta or {})
    meta["compat_mode"] = "native_worker"
    return WorkerResultCard(
        task_id=result.task_id,
        hypothesis_id=result.hypothesis_id,
        worker_kind=result.worker_kind,
        status=result.status,
        confidence=result.confidence,
        summary=result.summary,
        evidence=list(result.evidence or []),
        escalate_to_chief=result.escalate_to_chief,
        meta=meta,
    )


async def _run_index_reference_worker(
    *,
    task: WorkerTaskCard,
    db,
) -> WorkerResultCard:
    from services.audit.index_audit import (
        _apply_index_finding,
        _collect_index_issue_candidates,
        _index_ai_review_enabled,
        _index_issue_evidence,
        _review_index_issue_candidates_async,
        _reviewable_index_issue,
        build_index_alias_map,
        load_active_skill_rules,
    )

    project_id = str(task.context.get("project_id") or "").strip()
    audit_version = int(task.context.get("audit_version") or 0)
    alias_map = build_index_alias_map(load_active_skill_rules(db, skill_type="index"))
    issue_candidates = _collect_index_issue_candidates(
        project_id,
        audit_version,
        db,
        alias_map=alias_map,
        source_sheet_filters=[task.source_sheet_no] if str(task.source_sheet_no or "").strip() else None,
        target_sheet_filters=list(task.target_sheet_nos or []),
    )
    if not issue_candidates:
        return _build_native_result(
            task=task,
            status="rejected",
            confidence=0.74,
            summary=f"原生索引副审未发现 {task.source_sheet_no} 指向目标图的索引问题",
            rule_id="index_visual_review",
            evidence_pack_id="overview_pack",
        )

    skill_profile = load_runtime_skill_profile(
        db,
        skill_type="index",
        stage_key="index_visual_review",
    )
    feedback_profile = load_feedback_runtime_profile(db, issue_type="index")
    reviewable_candidates = [
        candidate
        for candidate in issue_candidates
        if _reviewable_index_issue(str(candidate.get("review_kind") or "").strip())
    ]
    final_candidates = [
        candidate
        for candidate in issue_candidates
        if not _reviewable_index_issue(str(candidate.get("review_kind") or "").strip())
    ]
    if _index_ai_review_enabled():
        final_candidates.extend(
            await _review_index_issue_candidates_async(
                project_id,
                db,
                reviewable_candidates,
                audit_version=audit_version or None,
                skill_profile=skill_profile,
                feedback_profile=feedback_profile,
            )
        )
    else:
        final_candidates.extend(reviewable_candidates)

    issues = []
    for candidate in final_candidates:
        try:
            issue = _apply_index_finding(candidate["issue"], candidate)
        except Exception:
            continue
        issues.append(issue)

    if not issues:
        return _build_native_result(
            task=task,
            status="rejected",
            confidence=0.7,
            summary=f"原生索引副审已复核 {task.source_sheet_no}，当前更像误报或证据不足",
            rule_id="index_visual_review",
            evidence_pack_id="overview_pack",
        )

    evidence = [_index_issue_evidence(issue) for issue in issues[:5]]
    first = evidence[0]
    confidence_values = [
        float(issue.confidence)
        for issue in issues
        if isinstance(issue.confidence, (int, float))
    ]
    confidence = max(confidence_values) if confidence_values else 0.82
    status = "confirmed"
    if any(str(issue.finding_status or "").strip().lower() == "needs_review" for issue in issues):
        status = "needs_review"
    return WorkerResultCard(
        task_id=task.id,
        hypothesis_id=task.hypothesis_id,
        worker_kind=task.worker_kind,
        status=status,
        confidence=confidence,
        summary=str(issues[0].description or f"原生索引副审返回 {len(issues)} 处索引问题").strip(),
        evidence=evidence,
        escalate_to_chief=(status == "needs_review"),
        meta={
            "compat_mode": "native_worker",
            "sheet_no": first["sheet_no"],
            "location": first["location"],
            "rule_id": first["rule_id"],
            "evidence_pack_id": first["evidence_pack_id"],
            "severity": first["severity"],
            "issue_count": len(issues),
            "review_round": max(int(issue.review_round or 1) for issue in issues),
        },
    )


async def _run_material_semantic_worker(
    *,
    task: WorkerTaskCard,
    db,
) -> WorkerResultCard:
    from services.audit.material_audit import (
        _apply_material_finding,
        _collect_material_rule_issues_and_ai_jobs,
        _material_issue_evidence,
        _norm_material_code,
        _run_material_ai_review,
        _run_material_ai_reviews_bounded,
        resolve_material_issue_severity,
    )

    project_id = str(task.context.get("project_id") or "").strip()
    audit_version = int(task.context.get("audit_version") or 0)
    skill_profile = load_runtime_skill_profile(
        db,
        skill_type="material",
        stage_key="material_consistency_review",
    )
    feedback_profile = load_feedback_runtime_profile(db, issue_type="material")
    rule_issues, ai_review_jobs = _collect_material_rule_issues_and_ai_jobs(
        project_id,
        audit_version,
        db,
        sheet_filters=[task.source_sheet_no] if str(task.source_sheet_no or "").strip() else None,
    )

    issues = []
    for issue in rule_issues:
        try:
            issues.append(_apply_material_finding(issue))
        except Exception:
            continue

    if ai_review_jobs:
        try:
            all_ai_results = await _run_material_ai_reviews_bounded(ai_review_jobs, _run_material_ai_review)
        except Exception:
            all_ai_results = [[] for _ in ai_review_jobs]

        for job, ai_items in zip(ai_review_jobs, all_ai_results):
            anchor_map = dict(job.get("material_anchor_by_code") or {})
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
                synthetic_issue = type("MaterialIssue", (), {})()
                synthetic_issue.project_id = project_id
                synthetic_issue.audit_version = audit_version
                synthetic_issue.type = "material"
                synthetic_issue.severity = severity
                synthetic_issue.sheet_no_a = job["sheet_no"]
                synthetic_issue.sheet_no_b = None
                synthetic_issue.location = location
                synthetic_issue.description = description
                synthetic_issue.evidence_json = json.dumps(
                    {
                        "anchors": [anchor] if anchor else [],
                        "unlocated_reason": None if anchor else "material_ai_issue_unlocated",
                    },
                    ensure_ascii=False,
                )
                try:
                    issues.append(_apply_material_finding(synthetic_issue))
                except Exception:
                    continue

    if not issues:
        return _build_native_result(
            task=task,
            status="rejected",
            confidence=0.72,
            summary=f"原生材料副审未发现 {task.source_sheet_no} 的材料问题",
            rule_id="material_consistency_review",
            evidence_pack_id="focus_pack",
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
        summary=str(issues[0].description or f"原生材料副审返回 {len(issues)} 处材料问题").strip(),
        evidence=evidence,
        meta={
            "compat_mode": "native_worker",
            "sheet_no": first["sheet_no"],
            "location": first["location"],
            "rule_id": first["rule_id"],
            "evidence_pack_id": first["evidence_pack_id"],
            "severity": first["severity"],
            "issue_count": len(issues),
            "review_round": max(int(issue.review_round or 1) for issue in issues),
        },
    )


async def _run_dimension_consistency_worker(
    *,
    task: WorkerTaskCard,
    db,
) -> WorkerResultCard:
    from services.audit.dimension_audit import (
        _collect_dimension_pair_issues_async,
        _dimension_issue_evidence,
    )

    project_id = str(task.context.get("project_id") or "").strip()
    audit_version = int(task.context.get("audit_version") or 0)
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
    )
    if not issues:
        return _build_native_result(
            task=task,
            status="rejected",
            confidence=0.72,
            summary=f"原生尺寸副审未发现 {task.source_sheet_no} 与目标图之间的尺寸问题",
            rule_id="dimension_pair_compare",
            evidence_pack_id="paired_overview_pack",
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
    return WorkerResultCard(
        task_id=task.id,
        hypothesis_id=task.hypothesis_id,
        worker_kind=task.worker_kind,
        status=status,
        confidence=confidence,
        summary=str(issues[0].description or f"原生尺寸副审返回 {len(issues)} 处尺寸问题").strip(),
        evidence=evidence,
        escalate_to_chief=(status == "needs_review"),
        meta={
            "compat_mode": "native_worker",
            "sheet_no": first["sheet_no"],
            "location": first["location"],
            "rule_id": first["rule_id"],
            "evidence_pack_id": first["evidence_pack_id"],
            "severity": first["severity"],
            "issue_count": len(issues),
            "review_round": max(int(issue.review_round or 1) for issue in issues),
        },
    )


__all__ = ["run_native_review_worker"]
