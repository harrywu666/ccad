"""Runner 原始输出落盘。"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict


def _artifact_dir() -> Path:
    raw = str(os.getenv("CCAD_RUNNER_RAW_OUTPUT_DIR", "") or "").strip()
    path = Path(raw).expanduser() if raw else Path("/tmp/ccad_runner_raw_outputs")
    path.mkdir(parents=True, exist_ok=True)
    return path


def _safe_token(value: str, default: str) -> str:
    text = str(value or "").strip()
    if not text:
        return default
    normalized = re.sub(r"[^0-9A-Za-z_.-]+", "_", text)
    normalized = normalized.strip("._")
    return normalized or default


def save_runner_raw_output(
    *,
    project_id: str,
    audit_version: int,
    agent_key: str,
    turn_kind: str,
    session_key: str,
    provider_name: str,
    provider_mode: str,
    status: str,
    raw_output: str,
    meta: Dict[str, Any] | None = None,
) -> Path | None:
    content = str(raw_output or "")
    if not content.strip():
        return None

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    file_name = "__".join(
        [
            _safe_token(project_id, "project"),
            str(int(audit_version)),
            _safe_token(agent_key, "agent"),
            _safe_token(turn_kind, "turn"),
            _safe_token(session_key, "session"),
            timestamp,
        ]
    ) + ".json"

    path = _artifact_dir() / file_name
    payload = {
        "project_id": project_id,
        "audit_version": int(audit_version),
        "agent_key": agent_key,
        "turn_kind": turn_kind,
        "session_key": session_key,
        "provider_name": provider_name,
        "provider_mode": provider_mode,
        "status": status,
        "created_at": datetime.now().isoformat(),
        "meta": meta or {},
        "raw_output": content,
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


__all__ = ["save_runner_raw_output"]
