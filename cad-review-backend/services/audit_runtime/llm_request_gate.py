"""项目级 LLM 调用总闸门。"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Tuple

from services.audit_runtime.cancel_registry import AuditCancellationRequested


def _read_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _default_parallel_limit(provider_mode: str) -> int:
    normalized = str(provider_mode or "").strip().lower()
    if normalized in {"sdk", "kimi_sdk", "api", "cli"}:
        return 1
    return 1


def _default_min_interval_seconds(provider_mode: str) -> float:
    normalized = str(provider_mode or "").strip().lower()
    if normalized in {"sdk", "kimi_sdk", "api", "cli"}:
        return 0.0
    return 0.0


def _gate_parallel_limit(provider_mode: str) -> int:
    value = _read_int_env(
        "AUDIT_PROJECT_LLM_MAX_CONCURRENCY",
        _default_parallel_limit(provider_mode),
    )
    return max(1, min(16, value))


def _gate_min_interval_seconds(provider_mode: str) -> float:
    value = _read_float_env(
        "AUDIT_PROJECT_LLM_MIN_INTERVAL_SECONDS",
        _default_min_interval_seconds(provider_mode),
    )
    return max(0.0, min(60.0, value))


def _gate_poll_interval_seconds() -> float:
    value = _read_float_env("AUDIT_PROJECT_LLM_GATE_POLL_SECONDS", 0.2)
    return max(0.05, min(5.0, value))


@dataclass(frozen=True)
class GateKey:
    project_id: str
    audit_version: int
    provider_mode: str


class ProjectLlmRequestGate:
    def __init__(
        self,
        *,
        project_id: str,
        audit_version: int,
        provider_mode: str,
        max_concurrency: int,
        min_interval_seconds: float,
    ) -> None:
        self.project_id = project_id
        self.audit_version = int(audit_version)
        self.provider_mode = provider_mode
        self.max_concurrency = max(1, int(max_concurrency or 1))
        self.min_interval_seconds = max(0.0, float(min_interval_seconds or 0.0))
        self._semaphore = threading.BoundedSemaphore(self.max_concurrency)
        self._pacing_lock = threading.Lock()
        self._last_started_at = 0.0

    async def acquire(self, *, should_cancel=None):  # noqa: ANN001
        poll = _gate_poll_interval_seconds()
        while True:
            acquired = await asyncio.to_thread(self._semaphore.acquire, True, poll)
            if acquired:
                break
            if should_cancel and should_cancel():
                raise AuditCancellationRequested("用户手动中断审核")

        try:
            await self._wait_for_spacing(should_cancel=should_cancel)
        except Exception:
            self._semaphore.release()
            raise

        def _release() -> None:
            self._semaphore.release()

        return _release

    async def _wait_for_spacing(self, *, should_cancel=None) -> None:  # noqa: ANN001
        while True:
            wait_seconds = 0.0
            with self._pacing_lock:
                now = time.monotonic()
                elapsed = now - self._last_started_at
                wait_seconds = max(0.0, self.min_interval_seconds - elapsed)
                if wait_seconds <= 0:
                    self._last_started_at = now
                    return

            if should_cancel and should_cancel():
                raise AuditCancellationRequested("用户手动中断审核")
            await asyncio.sleep(min(wait_seconds, _gate_poll_interval_seconds()))


_GATES: Dict[GateKey, ProjectLlmRequestGate] = {}
_GATES_LOCK = threading.Lock()


def get_project_llm_gate(
    *,
    project_id: str,
    audit_version: int,
    provider_mode: str,
) -> ProjectLlmRequestGate:
    normalized_mode = str(provider_mode or "").strip().lower() or "unknown"
    key = GateKey(
        project_id=str(project_id or "").strip(),
        audit_version=int(audit_version),
        provider_mode=normalized_mode,
    )
    with _GATES_LOCK:
        gate = _GATES.get(key)
        if gate is None:
            gate = ProjectLlmRequestGate(
                project_id=key.project_id,
                audit_version=key.audit_version,
                provider_mode=key.provider_mode,
                max_concurrency=_gate_parallel_limit(normalized_mode),
                min_interval_seconds=_gate_min_interval_seconds(normalized_mode),
            )
            _GATES[key] = gate
        return gate


def clear_project_llm_gates() -> None:
    with _GATES_LOCK:
        _GATES.clear()


__all__ = [
    "ProjectLlmRequestGate",
    "clear_project_llm_gates",
    "get_project_llm_gate",
]
