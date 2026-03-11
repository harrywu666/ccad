"""设置页里的审核运行总结。"""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List

from sqlalchemy.orm import Session

from models import AuditRun, AuditRunEvent, Project

_ENDED_STATUSES = {"done", "failed", "cancelled"}
_NOTE_EVENT_KINDS = {
    "agent_status_reported",
    "runner_help_requested",
    "runner_help_resolved",
    "runner_observer_action",
    "output_validation_failed",
}


def _safe_meta(raw: str | None) -> Dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _duration_seconds(run: AuditRun) -> int | None:
    started_at = getattr(run, "started_at", None)
    finished_at = getattr(run, "finished_at", None)
    if not started_at or not finished_at:
        return None
    try:
        return max(0, int((finished_at - started_at).total_seconds()))
    except Exception:
        return None


def _is_ended_run(run: AuditRun) -> bool:
    status = str(getattr(run, "status", "") or "").strip().lower()
    return bool(getattr(run, "finished_at", None)) or status in _ENDED_STATUSES


def list_audit_runtime_summaries(db: Session, *, limit: int = 10) -> Dict[str, Any]:
    runs = (
        db.query(AuditRun, Project.name.label("project_name"))
        .join(Project, Project.id == AuditRun.project_id)
        .order_by(
            AuditRun.finished_at.desc().nullslast(),
            AuditRun.updated_at.desc(),
            AuditRun.id.desc(),
        )
        .limit(max(1, min(int(limit), 50)) * 3)
        .all()
    )

    items: List[Dict[str, Any]] = []
    for run, project_name in runs:
        if not _is_ended_run(run):
            continue

        events = (
            db.query(AuditRunEvent)
            .filter(
                AuditRunEvent.project_id == run.project_id,
                AuditRunEvent.audit_version == run.audit_version,
            )
            .order_by(AuditRunEvent.id.asc())
            .all()
        )

        counts = defaultdict(int)
        agent_map: Dict[str, Dict[str, Any]] = {}
        recent_notes: List[Dict[str, Any]] = []

        for event in events:
            event_kind = str(event.event_kind or "").strip()
            counts[event_kind] += 1
            meta = _safe_meta(event.meta_json)

            if event_kind == "agent_status_reported":
                agent_key = str(event.agent_key or "").strip() or "unknown_agent"
                entry = agent_map.setdefault(
                    agent_key,
                    {
                        "agent_key": agent_key,
                        "agent_name": str(event.agent_name or agent_key).strip(),
                        "report_count": 0,
                        "help_requested_count": 0,
                        "help_resolved_count": 0,
                        "output_unstable_count": 0,
                    },
                )
                entry["report_count"] += 1

            if event_kind in {"runner_help_requested", "runner_help_resolved"}:
                source_agent_key = str(meta.get("source_agent_key") or "").strip() or "unknown_agent"
                entry = agent_map.setdefault(
                    source_agent_key,
                    {
                        "agent_key": source_agent_key,
                        "agent_name": source_agent_key,
                        "report_count": 0,
                        "help_requested_count": 0,
                        "help_resolved_count": 0,
                        "output_unstable_count": 0,
                    },
                )
                if event_kind == "runner_help_requested":
                    entry["help_requested_count"] += 1
                else:
                    entry["help_resolved_count"] += 1

            if event_kind == "output_validation_failed":
                agent_key = str(event.agent_key or "").strip() or "unknown_agent"
                entry = agent_map.setdefault(
                    agent_key,
                    {
                        "agent_key": agent_key,
                        "agent_name": str(event.agent_name or agent_key).strip(),
                        "report_count": 0,
                        "help_requested_count": 0,
                        "help_resolved_count": 0,
                        "output_unstable_count": 0,
                    },
                )
                entry["output_unstable_count"] += 1

            if event_kind in _NOTE_EVENT_KINDS:
                recent_notes.append(
                    {
                        "event_kind": event_kind,
                        "message": str(event.message or "").strip(),
                        "agent_name": str(event.agent_name or "").strip() or None,
                        "created_at": _iso(event.created_at),
                    }
                )

        agent_summaries = sorted(
            agent_map.values(),
            key=lambda item: (
                -int(item["help_requested_count"]),
                -int(item["report_count"]),
                item["agent_key"],
            ),
        )

        items.append(
            {
                "project_id": run.project_id,
                "project_name": project_name,
                "audit_version": run.audit_version,
                "status": run.status,
                "current_step": run.current_step,
                "provider_mode": run.provider_mode,
                "started_at": _iso(run.started_at),
                "finished_at": _iso(run.finished_at),
                "duration_seconds": _duration_seconds(run),
                "counts": {
                    "agent_status_reported": counts["agent_status_reported"],
                    "runner_help_requested": counts["runner_help_requested"],
                    "runner_help_resolved": counts["runner_help_resolved"],
                    "output_validation_failed": counts["output_validation_failed"],
                    "runner_observer_action": counts["runner_observer_action"],
                },
                "agent_summaries": agent_summaries,
                "recent_notes": recent_notes[-5:],
            }
        )
        if len(items) >= max(1, min(int(limit), 50)):
            break

    return {"items": items}
