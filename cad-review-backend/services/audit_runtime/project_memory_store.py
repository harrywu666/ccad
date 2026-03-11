"""项目级主审记忆存储。"""

from __future__ import annotations

import json
from typing import Any, Dict, Optional

from models import ProjectMemoryRecord


def load_project_memory_record(db, *, project_id: str, audit_version: int) -> Optional[Dict[str, Any]]:  # noqa: ANN001
    row = (
        db.query(ProjectMemoryRecord)
        .filter(
            ProjectMemoryRecord.project_id == project_id,
            ProjectMemoryRecord.audit_version == audit_version,
        )
        .first()
    )
    if row is None:
        return None
    payload = json.loads(row.memory_json or "{}")
    return payload if isinstance(payload, dict) else None


def save_project_memory_record(
    db,
    *,
    project_id: str,
    audit_version: int,
    payload: Dict[str, Any],
):  # noqa: ANN001
    row = (
        db.query(ProjectMemoryRecord)
        .filter(
            ProjectMemoryRecord.project_id == project_id,
            ProjectMemoryRecord.audit_version == audit_version,
        )
        .first()
    )
    if row is None:
        row = ProjectMemoryRecord(
            project_id=project_id,
            audit_version=audit_version,
        )
        db.add(row)

    row.memory_json = json.dumps(payload, ensure_ascii=False)
    db.commit()
    db.refresh(row)
    return row


__all__ = [
    "load_project_memory_record",
    "save_project_memory_record",
]
