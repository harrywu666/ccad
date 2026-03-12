"""项目级 LLM 调用总闸门。"""

from __future__ import annotations

import asyncio
import os
import threading
import time
from dataclasses import dataclass
from typing import Dict, Iterable, Tuple

from services.audit_runtime.cancel_registry import AuditCancellationRequested


def _first_env(names: Iterable[str]) -> str | None:
    for name in names:
        raw = os.getenv(name)
        if raw is None:
            continue
        value = str(raw).strip()
        if value:
            return value
    return None


def _read_float_env(name: str, default: float) -> float:
    return _read_first_float_env((name,), default)


def _read_first_int_env(names: Iterable[str], default: int) -> int:
    raw = _first_env(names)
    if raw is None:
        return default
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _read_first_float_env(names: Iterable[str], default: float) -> float:
    raw = _first_env(names)
    if raw is None:
        return default
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return default


def _read_int_env(name: str, default: int) -> int:
    return _read_first_int_env((name,), default)


def _api_backend_key() -> str:
    raw = str(os.getenv("KIMI_PROVIDER", "official") or "official").strip().lower()
    if raw in {"openrouter", "open_router"}:
        return "openrouter"
    if raw in {"official", "moonshot", "openai"}:
        return "official_api"
    return "api"


def resolve_llm_gate_provider_key(
    *,
    provider_mode: str | None,
    provider_name: str | None = None,
) -> str:
    normalized_mode = str(provider_mode or "").strip().lower()
    normalized_name = str(provider_name or "").strip().lower()

    if normalized_mode in {"sdk", "kimi_sdk"} or normalized_name == "sdk":
        return "kimi_sdk"
    if normalized_mode in {"cli"} or normalized_name == "cli":
        return "cli"
    if normalized_mode in {"openrouter", "openrouter_api"}:
        return "openrouter"
    if normalized_mode in {"api", "kimi_api"} or normalized_name == "api":
        return _api_backend_key()
    if normalized_mode:
        return normalized_mode
    if normalized_name:
        return normalized_name
    return "unknown"


def _default_parallel_limit(provider_key: str) -> int:
    normalized = str(provider_key or "").strip().lower()
    if normalized == "openrouter":
        return 2
    if normalized in {"kimi_sdk", "official_api", "api", "cli"}:
        return 1
    return 1


def _default_min_interval_seconds(provider_key: str) -> float:
    normalized = str(provider_key or "").strip().lower()
    if normalized in {"openrouter", "kimi_sdk", "official_api", "api", "cli"}:
        return 0.0
    return 0.0


def _gate_parallel_limit(provider_key: str) -> int:
    normalized = str(provider_key or "").strip().lower()
    env_names = ["AUDIT_PROJECT_LLM_MAX_CONCURRENCY"]
    if normalized == "openrouter":
        env_names.insert(0, "AUDIT_PROJECT_OPENROUTER_MAX_CONCURRENCY")
    elif normalized == "kimi_sdk":
        env_names.insert(0, "AUDIT_PROJECT_KIMI_SDK_MAX_CONCURRENCY")

    value = _read_first_int_env(
        env_names,
        _default_parallel_limit(normalized),
    )
    return max(1, min(16, value))


def _gate_min_interval_seconds(provider_key: str) -> float:
    normalized = str(provider_key or "").strip().lower()
    env_names = ["AUDIT_PROJECT_LLM_MIN_INTERVAL_SECONDS"]
    if normalized == "openrouter":
        env_names.insert(0, "AUDIT_PROJECT_OPENROUTER_MIN_INTERVAL_SECONDS")
    elif normalized == "kimi_sdk":
        env_names.insert(0, "AUDIT_PROJECT_KIMI_SDK_MIN_INTERVAL_SECONDS")

    value = _read_first_float_env(
        env_names,
        _default_min_interval_seconds(normalized),
    )
    return max(0.0, min(60.0, value))


def _gate_poll_interval_seconds() -> float:
    value = _read_float_env("AUDIT_PROJECT_LLM_GATE_POLL_SECONDS", 0.2)
    return max(0.05, min(5.0, value))


@dataclass(frozen=True)
class GateKey:
    project_id: str
    audit_version: int
    provider_key: str


class ProjectLlmRequestGate:
    def __init__(
        self,
        *,
        project_id: str,
        audit_version: int,
        provider_key: str,
        max_concurrency: int,
        min_interval_seconds: float,
    ) -> None:
        self.project_id = project_id
        self.audit_version = int(audit_version)
        self.provider_key = provider_key
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
    provider_name: str | None = None,
) -> ProjectLlmRequestGate:
    provider_key = resolve_llm_gate_provider_key(
        provider_mode=provider_mode,
        provider_name=provider_name,
    )
    key = GateKey(
        project_id=str(project_id or "").strip(),
        audit_version=int(audit_version),
        provider_key=provider_key,
    )
    with _GATES_LOCK:
        gate = _GATES.get(key)
        if gate is None:
            gate = ProjectLlmRequestGate(
                project_id=key.project_id,
                audit_version=key.audit_version,
                provider_key=key.provider_key,
                max_concurrency=_gate_parallel_limit(provider_key),
                min_interval_seconds=_gate_min_interval_seconds(provider_key),
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
    "resolve_llm_gate_provider_key",
]
