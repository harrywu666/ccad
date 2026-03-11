"""纯代码 Runner 守护层。"""

from __future__ import annotations

import time
from dataclasses import asdict
from typing import Any, Dict

from services.audit_runtime.runner_heartbeat import get_runner_heartbeat, touch_runner_heartbeat
from services.audit_runtime.runner_observer_session import ProjectRunnerObserverSession
from services.audit_runtime.runner_observer_types import RunnerObserverMemory
from services.audit_runtime.runner_snapshot_store import load_runner_snapshot


class RunnerGuardian:
    """只负责看 Runner 心跳和快照，不做业务判断。"""

    def __init__(self, *, timeout_seconds: int = 120) -> None:
        self.timeout_seconds = int(timeout_seconds)

    def check_and_recover(
        self,
        project_id: str,
        audit_version: int,
        *,
        provider=None,  # noqa: ANN001
    ) -> Dict[str, Any]:
        last_heartbeat = get_runner_heartbeat(project_id, audit_version)
        now = time.time()
        if last_heartbeat and now - last_heartbeat <= self.timeout_seconds:
            return {"restarted": False, "reason": "heartbeat_fresh"}

        snapshot = load_runner_snapshot(project_id, audit_version)
        if not snapshot:
            return {"restarted": False, "reason": "snapshot_missing"}

        session = ProjectRunnerObserverSession.get_or_create(
            project_id,
            audit_version=int(audit_version),
            provider=provider,
        )
        memory_payload = snapshot.get("memory") or {}
        memory = RunnerObserverMemory(
            project_id=project_id,
            audit_version=int(audit_version),
            project_summary=str(memory_payload.get("project_summary") or "").strip(),
            current_focus=str(memory_payload.get("current_focus") or "").strip(),
            recent_events=list(memory_payload.get("recent_events") or []),
            recent_decisions=list(memory_payload.get("recent_decisions") or []),
            intervention_history=list(memory_payload.get("intervention_history") or []),
            master_status_summary=dict(memory_payload.get("master_status_summary") or {}),
        )
        session.memory = memory
        touch_runner_heartbeat(project_id, audit_version)
        return {
            "restarted": True,
            "run_mode": snapshot.get("run_mode") or memory_payload.get("run_mode"),
            "memory": asdict(memory),
        }


__all__ = ["RunnerGuardian"]
