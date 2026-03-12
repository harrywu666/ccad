"""材料一致性副审 skill。"""

from __future__ import annotations

import json

from services.audit import material_audit
from services.audit_runtime.worker_skill_contract import build_worker_skill_result
from services.audit_runtime.worker_skill_loader import WorkerSkillBundle, load_worker_skill
from services.feedback_runtime_service import load_feedback_runtime_profile
from services.skill_pack_service import load_runtime_skill_profile


async def run_material_semantic_skill(
    *,
    task,
    db,
    skill_bundle: WorkerSkillBundle | None = None,
):
    skill = skill_bundle or load_worker_skill("material_semantic_consistency")
    project_id = str(task.context.get("project_id") or "").strip()
    audit_version = int(task.context.get("audit_version") or 0)
    skill_profile = load_runtime_skill_profile(
        db,
        skill_type="material",
        stage_key="material_consistency_review",
    )
    feedback_profile = load_feedback_runtime_profile(db, issue_type="material")
    rule_issues, ai_review_jobs = material_audit._collect_material_rule_issues_and_ai_jobs(
        project_id,
        audit_version,
        db,
        sheet_filters=[task.source_sheet_no] if str(task.source_sheet_no or "").strip() else None,
    )

    issues = []
    for issue in rule_issues:
        try:
            issues.append(material_audit._apply_material_finding(issue))
        except Exception:
            continue

    if ai_review_jobs:
        try:
            all_ai_results = await material_audit._run_material_ai_reviews_bounded(
                ai_review_jobs,
                material_audit._run_material_ai_review,
            )
        except Exception:
            all_ai_results = [[] for _ in ai_review_jobs]

        for job, ai_items in zip(ai_review_jobs, all_ai_results):
            anchor_map = dict(job.get("material_anchor_by_code") or {})
            for item in ai_items:
                severity = material_audit.resolve_material_issue_severity(
                    str(item.get("severity") or "warning").strip() or "warning",
                    skill_profile=skill_profile,
                    feedback_profile=feedback_profile,
                )
                location = str(item.get("location") or f"材料{item.get('material_code') or '?'}").strip()
                description = str(item.get("description") or "").strip()
                if not description:
                    continue
                evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
                code_key = material_audit._norm_material_code(
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
                    issues.append(material_audit._apply_material_finding(synthetic_issue))
                except Exception:
                    continue

    if not issues:
        return build_worker_skill_result(
            task=task,
            skill_bundle=skill,
            status="rejected",
            confidence=0.72,
            summary=f"原生材料副审未发现 {task.source_sheet_no} 的材料问题",
            rule_id="material_consistency_review",
            evidence_pack_id="focus_pack",
        )

    evidence = [material_audit._material_issue_evidence(issue) for issue in issues[:5]]
    first = evidence[0]
    confidence_values = [
        float(issue.confidence)
        for issue in issues
        if isinstance(issue.confidence, (int, float))
    ]
    confidence = max(confidence_values) if confidence_values else 0.83
    return build_worker_skill_result(
        task=task,
        skill_bundle=skill,
        status="confirmed",
        confidence=confidence,
        summary=str(issues[0].description or f"原生材料副审返回 {len(issues)} 处材料问题").strip(),
        rule_id=str(first["rule_id"]),
        evidence_pack_id=str(first["evidence_pack_id"]),
        evidence=evidence,
        meta={
            "sheet_no": first["sheet_no"],
            "location": first["location"],
            "severity": first["severity"],
            "issue_count": len(issues),
            "review_round": max(int(issue.review_round or 1) for issue in issues),
        },
    )


__all__ = ["run_material_semantic_skill"]
