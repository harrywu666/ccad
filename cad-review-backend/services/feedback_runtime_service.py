"""误报经验运行时服务。"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime
from typing import Any, Dict

from models import FeedbackSample


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

    return {
        "issue_type": issue_type,
        "sample_count": len(rows),
        "false_positive_rate": false_positive_rate,
        "confidence_floor": confidence_floor,
        "needs_secondary_review": needs_review or false_positive_rate >= 0.5,
        "severity_override": severity_override,
    }


def update_feedback_sample_curation(sample: FeedbackSample, curation_status: str) -> None:
    sample.curation_status = curation_status
    sample.curated_at = datetime.now() if curation_status != "new" else None


def refresh_runtime_feedback_index(*, project_id: str | None = None, issue_type: str | None = None) -> Dict[str, Any]:
    """运行时经验层刷新入口。

    当前版本直接读数据库，这里只返回刷新请求摘要，给路由和后续缓存化预留统一入口。
    """
    return {
        "refreshed": True,
        "project_id": project_id,
        "issue_type": issue_type,
    }
