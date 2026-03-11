"""Runner 快照存储。"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict


def _snapshot_dir() -> Path:
    raw = os.getenv("CCAD_RUNNER_SNAPSHOT_DIR")
    if raw:
        path = Path(raw)
    else:
        path = Path("/tmp/ccad_runner_snapshots")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _snapshot_path(project_id: str, audit_version: int) -> Path:
    safe_project = str(project_id).replace("/", "_")
    return _snapshot_dir() / f"{safe_project}_{int(audit_version)}.json"


def write_runner_snapshot(project_id: str, audit_version: int, payload: Dict[str, Any]) -> Path:
    path = _snapshot_path(project_id, audit_version)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def load_runner_snapshot(project_id: str, audit_version: int) -> Dict[str, Any] | None:
    path = _snapshot_path(project_id, audit_version)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


__all__ = [
    "write_runner_snapshot",
    "load_runner_snapshot",
]
