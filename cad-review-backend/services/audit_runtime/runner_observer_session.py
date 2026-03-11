"""项目级 Runner Observer Agent 长会话。"""

from __future__ import annotations

from dataclasses import asdict
import threading
import time
from typing import Dict, Tuple

from services.audit_runtime.llm_request_gate import get_project_llm_gate
from services.audit_runtime.runner_heartbeat import touch_runner_heartbeat
from services.audit_runtime.runner_snapshot_store import write_runner_snapshot
from services.audit_runtime.runner_observer_types import (
    RunnerObserverDecision,
    RunnerObserverFeedSnapshot,
    RunnerObserverMemory,
)


class ProjectRunnerObserverSession:
    """每个项目一条的 Runner Observer 长会话。"""

    _registry: Dict[Tuple[str, int], "ProjectRunnerObserverSession"] = {}
    _registry_lock = threading.Lock()

    def __init__(
        self,
        project_id: str,
        audit_version: int,
        provider,
        *,
        provider_mode: str | None = None,
    ) -> None:  # noqa: ANN001
        self.project_id = project_id
        self.audit_version = int(audit_version)
        self.provider = provider
        self.provider_mode = str(provider_mode or getattr(provider, "provider_name", "unknown")).strip() or "unknown"
        self._last_observed_at = 0.0
        self._observe_lock = threading.Lock()
        self.memory = RunnerObserverMemory(
            project_id=project_id,
            audit_version=int(audit_version),
        )

    @classmethod
    def get_or_create(
        cls,
        project_id: str,
        *,
        audit_version: int,
        provider,
        provider_mode: str | None = None,
    ) -> "ProjectRunnerObserverSession":  # noqa: ANN001
        key = (project_id, int(audit_version))
        with cls._registry_lock:
            session = cls._registry.get(key)
            if session is None:
                session = cls(project_id, audit_version, provider, provider_mode=provider_mode)
                cls._registry[key] = session
            elif provider is not None:
                session.provider = provider
            if provider_mode:
                session.provider_mode = str(provider_mode).strip() or session.provider_mode
            return session

    @classmethod
    def clear_registry(cls) -> None:
        with cls._registry_lock:
            cls._registry.clear()

    async def observe(
        self,
        snapshot: RunnerObserverFeedSnapshot,
    ) -> RunnerObserverDecision:
        touch_runner_heartbeat(self.project_id, self.audit_version)
        gate = get_project_llm_gate(
            project_id=self.project_id,
            audit_version=self.audit_version,
            provider_mode=self.provider_mode,
        )
        release_llm_slot = await gate.acquire()
        try:
            decision = await self.provider.observe_once(snapshot, self.memory)
        finally:
            release_llm_slot()
        with self._observe_lock:
            self._last_observed_at = time.monotonic()
        self.memory.project_summary = decision.summary
        self.memory.current_focus = snapshot.current_step
        self.memory.recent_events = list(snapshot.recent_events)[-20:]
        self.memory.master_status_summary = dict(snapshot.runtime_status)
        self.memory.recent_decisions.append(
            {
                "summary": decision.summary,
                "risk_level": decision.risk_level,
                "suggested_action": decision.suggested_action,
                "should_intervene": decision.should_intervene,
                "confidence": decision.confidence,
            }
        )
        self.memory.recent_decisions = self.memory.recent_decisions[-20:]
        if decision.should_intervene:
            self.memory.intervention_history.append(
                {
                    "suggested_action": decision.suggested_action,
                    "reason": decision.reason,
                    "summary": decision.summary,
                }
            )
            self.memory.intervention_history = self.memory.intervention_history[-20:]
        write_runner_snapshot(
            self.project_id,
            self.audit_version,
            {
                "project_id": self.project_id,
                "audit_version": self.audit_version,
                "memory": asdict(self.memory),
            },
        )
        touch_runner_heartbeat(self.project_id, self.audit_version)
        return decision

    def should_observe(self) -> bool:
        min_interval = self._observer_min_interval_seconds()
        if min_interval <= 0:
            return True
        with self._observe_lock:
            if self._last_observed_at <= 0:
                return True
            return (time.monotonic() - self._last_observed_at) >= min_interval

    @staticmethod
    def _observer_min_interval_seconds() -> float:
        import os

        raw = os.getenv("AUDIT_RUNNER_OBSERVER_MIN_INTERVAL_SECONDS")
        if raw is None:
            return 20.0
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError):
            return 20.0
        return max(0.0, min(300.0, value))


__all__ = ["ProjectRunnerObserverSession"]
