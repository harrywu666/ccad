"""索引引用副审 skill。"""

from __future__ import annotations

from services.audit import index_audit
from services.audit_runtime.worker_skill_contract import (
    build_task_event_meta,
    build_worker_skill_result,
    extract_anchors_from_issue_results,
)
from services.audit_runtime.worker_skill_loader import WorkerSkillBundle, load_worker_skill
from services.audit_runtime.runtime_prompt_assembler import assemble_worker_runtime_prompt
from services.feedback_runtime_service import load_feedback_runtime_profile
from services.skill_pack_service import load_runtime_skill_profile


def _build_index_review_user_prompt(candidate: dict) -> str:
    return (
        "请复核这条索引疑点是否应当保留为审图问题。\n"
        f"来源图：{candidate['source_sheet_no']}\n"
        f"目标图：{candidate.get('target_sheet_no') or ''}\n"
        f"索引编号：{candidate['index_no']}\n"
        f"疑点类型：{candidate['review_kind']}\n"
        f"规则判断：{candidate['issue'].description}\n\n"
        "输出 JSON 对象，字段固定为：\n"
        '{"decision":"confirm|reject|uncertain","confidence":0.0,"reason":"","severity_override":""}'
    )


async def run_index_reference_skill(
    *,
    task,
    db,
    skill_bundle: WorkerSkillBundle | None = None,
):
    skill = skill_bundle or load_worker_skill("index_reference")
    event_meta = build_task_event_meta(task)
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
                prompt_builder=lambda candidate: assemble_worker_runtime_prompt(
                    worker_kind="index_reference",
                    task_context={
                        "source_sheet_no": candidate["source_sheet_no"],
                        "target_sheet_no": candidate.get("target_sheet_no") or "",
                        "index_no": candidate["index_no"],
                        "issue_kind": candidate["review_kind"],
                        "issue_description": candidate["issue"].description,
                    },
                    extra_meta=event_meta,
                    user_prompt_override=_build_index_review_user_prompt(candidate),
                ),
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
        },
    )


__all__ = ["run_index_reference_skill"]
