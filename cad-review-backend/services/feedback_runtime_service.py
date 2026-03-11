"""误报经验运行时服务。"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any, Dict

from models import AuditResult, FeedbackLearningRecord, FeedbackSample


@dataclass(frozen=True)
class ExperienceHint:
    rule_id: str
    false_positive_rate: float
    confidence_floor: float
    intervention_level: str
    reason_template: str | None = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _suggest_intervention_level(false_positive_rate: float, sample_count: int) -> str:
    if sample_count >= 5 and false_positive_rate >= 0.8:
        return "hard"
    if false_positive_rate >= 0.5:
        return "soft"
    return "advisory"


def load_feedback_runtime_profile(db, *, issue_type: str) -> Dict[str, Any]:
    rows = (
        db.query(FeedbackSample)
        .filter(
            FeedbackSample.issue_type == issue_type,
            FeedbackSample.curation_status == "accepted",
        )
        .order_by(FeedbackSample.curated_at.desc(), FeedbackSample.created_at.desc())
        .limit(20)
        .all()
    )

    if not rows:
        return {
            "issue_type": issue_type,
            "sample_count": 0,
            "false_positive_rate": 0.0,
            "confidence_floor": 0.0,
            "needs_secondary_review": False,
            "severity_override": None,
            "experience_hint": ExperienceHint(
                rule_id=f"{issue_type}_runtime_hint",
                false_positive_rate=0.0,
                confidence_floor=0.0,
                intervention_level="advisory",
                reason_template=None,
            ).to_dict(),
        }

    rates: list[float] = []
    floors: list[float] = []
    needs_review = False
    severity_votes: Counter[str] = Counter()

    for row in rows:
        try:
            snapshot = json.loads(row.snapshot_json or "{}")
        except Exception:
            snapshot = {}
        if not isinstance(snapshot, dict):
            snapshot = {}

        raw_rate = snapshot.get("false_positive_rate")
        if isinstance(raw_rate, (int, float)):
            rates.append(float(raw_rate))
        raw_floor = snapshot.get("confidence_floor")
        if isinstance(raw_floor, (int, float)):
            floors.append(float(raw_floor))
        if bool(snapshot.get("needs_secondary_review")):
            needs_review = True
        severity = str(snapshot.get("severity_override") or "").strip().lower()
        if severity:
            severity_votes[severity] += 1

    false_positive_rate = round(sum(rates) / len(rates), 3) if rates else min(0.9, round(len(rows) * 0.1, 3))
    confidence_floor = round(sum(floors) / len(floors), 3) if floors else round(min(0.95, 0.55 + false_positive_rate * 0.3), 3)
    severity_override = severity_votes.most_common(1)[0][0] if severity_votes else ("warning" if false_positive_rate >= 0.65 else None)

    hint = ExperienceHint(
        rule_id=f"{issue_type}_runtime_hint",
        false_positive_rate=false_positive_rate,
        confidence_floor=confidence_floor,
        intervention_level=_suggest_intervention_level(false_positive_rate, len(rows)),
        reason_template=(
            f"该类 {issue_type} 问题在历史反馈中误报较多，建议先提高判断门槛再决定是否升级处理。"
            if false_positive_rate >= 0.5
            else None
        ),
    )

    return {
        "issue_type": issue_type,
        "sample_count": len(rows),
        "false_positive_rate": false_positive_rate,
        "confidence_floor": confidence_floor,
        "needs_secondary_review": needs_review or false_positive_rate >= 0.5,
        "severity_override": severity_override,
        "experience_hint": hint.to_dict(),
    }


def update_feedback_sample_curation(sample: FeedbackSample, curation_status: str) -> None:
    sample.curation_status = curation_status
    sample.curated_at = datetime.now() if curation_status != "new" else None


def build_feedback_sample_snapshot_from_learning_record(
    learning_record: FeedbackLearningRecord,
) -> Dict[str, Any]:
    evidence_score = float(learning_record.evidence_score or 0.0)
    similar_case_count = int(learning_record.similar_case_count or 0)
    reusability_score = float(learning_record.reusability_score or 0.0)
    false_positive_rate = round(min(0.95, 0.45 + evidence_score * 0.25 + min(similar_case_count, 3) * 0.08), 3)
    confidence_floor = round(min(0.98, 0.55 + evidence_score * 0.35), 3)
    needs_secondary_review = evidence_score < 0.85 or similar_case_count < 2
    severity_override = "warning" if false_positive_rate >= 0.65 else None
    return {
        "source": "feedback_learning_record",
        "decision": learning_record.decision,
        "rule_id": learning_record.rule_id,
        "issue_type": learning_record.issue_type,
        "evidence_score": evidence_score,
        "similar_case_count": similar_case_count,
        "reusability_score": reusability_score,
        "false_positive_rate": false_positive_rate,
        "confidence_floor": confidence_floor,
        "needs_secondary_review": needs_secondary_review,
        "severity_override": severity_override,
    }


def sync_feedback_sample_from_learning_record(
    db,
    *,
    learning_record: FeedbackLearningRecord,
    audit_result: AuditResult,
    user_note: str | None = None,
) -> FeedbackSample | None:
    existing = (
        db.query(FeedbackSample)
        .filter(FeedbackSample.audit_result_id == learning_record.audit_result_id)
        .first()
    )

    if learning_record.decision not in {"accepted_for_learning", "accepted"}:
        if existing:
            db.delete(existing)
        return None

    snapshot = build_feedback_sample_snapshot_from_learning_record(learning_record)
    payload = {
        "project_id": learning_record.project_id,
        "audit_result_id": learning_record.audit_result_id,
        "audit_version": audit_result.audit_version,
        "issue_type": learning_record.issue_type or audit_result.type or "unknown",
        "severity": audit_result.severity,
        "sheet_no_a": audit_result.sheet_no_a,
        "sheet_no_b": audit_result.sheet_no_b,
        "location": audit_result.location,
        "description": audit_result.description,
        "evidence_json": audit_result.evidence_json,
        "value_a": audit_result.value_a,
        "value_b": audit_result.value_b,
        "user_note": user_note,
        "snapshot_json": json.dumps(snapshot, ensure_ascii=False),
        "curation_status": "accepted",
    }

    if existing:
        for key, value in payload.items():
            setattr(existing, key, value)
        existing.created_at = datetime.now()
        existing.curated_at = datetime.now()
        return existing

    sample = FeedbackSample(**payload)
    sample.curated_at = datetime.now()
    db.add(sample)
    return sample


def refresh_runtime_feedback_index(*, project_id: str | None = None, issue_type: str | None = None) -> Dict[str, Any]:
    """运行时经验层刷新入口。

    当前版本直接读数据库，这里只返回刷新请求摘要，给路由和后续缓存化预留统一入口。
    """
    return {
        "refreshed": True,
        "project_id": project_id,
        "issue_type": issue_type,
    }
