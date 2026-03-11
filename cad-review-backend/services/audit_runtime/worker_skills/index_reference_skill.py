"""索引引用副审 skill。"""

from __future__ import annotations

from services.audit import index_audit
from services.audit_runtime.worker_skill_contract import build_worker_skill_result
from services.audit_runtime.worker_skill_loader import WorkerSkillBundle, load_worker_skill
from services.feedback_runtime_service import load_feedback_runtime_profile
from services.skill_pack_service import load_runtime_skill_profile


async def run_index_reference_skill(
    *,
    task,
    db,
    skill_bundle: WorkerSkillBundle | None = None,
):
    skill = skill_bundle or load_worker_skill("index_reference")
    project_id = str(task.context.get("project_id") or "").strip()
    audit_version = int(task.context.get("audit_version") or 0)
    alias_map = index_audit.build_index_alias_map(index_audit.load_active_skill_rules(db, skill_type="index"))
    issue_candidates = index_audit._collect_index_issue_candidates(
        project_id,
        audit_version,
        db,
        alias_map=alias_map,
        source_sheet_filters=[task.source_sheet_no] if str(task.source_sheet_no or "").strip() else None,
        target_sheet_filters=list(task.target_sheet_nos or []),
    )
    if not issue_candidates:
        return build_worker_skill_result(
            task=task,
            skill_bundle=skill,
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
        if index_audit._reviewable_index_issue(str(candidate.get("review_kind") or "").strip())
    ]
    final_candidates = [
        candidate
        for candidate in issue_candidates
        if not index_audit._reviewable_index_issue(str(candidate.get("review_kind") or "").strip())
    ]
    if index_audit._index_ai_review_enabled():
        final_candidates.extend(
            await index_audit._review_index_issue_candidates_async(
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
            issue = index_audit._apply_index_finding(candidate["issue"], candidate)
        except Exception:
            continue
        issues.append(issue)

    if not issues:
        return build_worker_skill_result(
            task=task,
            skill_bundle=skill,
            status="rejected",
            confidence=0.7,
            summary=f"原生索引副审已复核 {task.source_sheet_no}，当前更像误报或证据不足",
            rule_id="index_visual_review",
            evidence_pack_id="overview_pack",
        )

    evidence = [index_audit._index_issue_evidence(issue) for issue in issues[:5]]
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
    return build_worker_skill_result(
        task=task,
        skill_bundle=skill,
        status=status,
        confidence=confidence,
        summary=str(issues[0].description or f"原生索引副审返回 {len(issues)} 处索引问题").strip(),
        rule_id=str(first["rule_id"]),
        evidence_pack_id=str(first["evidence_pack_id"]),
        evidence=evidence,
        escalate_to_chief=(status == "needs_review"),
        meta={
            "sheet_no": first["sheet_no"],
            "location": first["location"],
            "severity": first["severity"],
            "issue_count": len(issues),
            "review_round": max(int(issue.review_round or 1) for issue in issues),
        },
    )


__all__ = ["run_index_reference_skill"]
