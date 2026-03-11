from __future__ import annotations

import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.runner_snapshot_store import (  # type: ignore[attr-defined]
    load_runner_snapshot,
    write_runner_snapshot,
)


def test_runner_snapshot_store_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("CCAD_RUNNER_SNAPSHOT_DIR", str(tmp_path))

    write_runner_snapshot(
        "proj-snapshot",
        4,
        {
            "memory": {
                "project_summary": "当前流程稳定",
                "master_status_summary": {"current_step": "尺寸核对"},
            }
        },
    )

    payload = load_runner_snapshot("proj-snapshot", 4)

    assert payload is not None
    assert payload["memory"]["project_summary"] == "当前流程稳定"
    assert payload["memory"]["master_status_summary"]["current_step"] == "尺寸核对"

