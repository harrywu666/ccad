"""项目级常驻审图 Runner。"""

from __future__ import annotations

import asyncio
import inspect
import os
import threading
import time
from typing import Any, Dict, Optional, Tuple

from services.audit_runtime.output_guard import guard_output
from services.audit_runtime.cancel_registry import AuditCancellationRequested
from services.audit_runtime.llm_request_gate import get_project_llm_gate
from services.audit_runtime.providers.kimi_sdk_provider import SdkStreamIdleTimeoutError
from services.audit_runtime.raw_output_store import save_runner_raw_output
from services.audit_runtime.runner_broadcasts import build_runner_broadcast_message
from services.audit_runtime.runner_types import (
    ProviderStreamEvent,
    RunnerSubsession,
    RunnerTurnRequest,
    RunnerTurnResult,
)
from services.audit_runtime.visual_budget import get_active_visual_budget


class ProjectAuditAgentRunner:
    """项目级公共 Runner。

    第一版先提供：
    - 单例工厂
    - 项目级共享上下文
    - 按业务 Agent 隔离的子会话池
    """

    _registry: Dict[Tuple[str, int], "ProjectAuditAgentRunner"] = {}
    _registry_lock = threading.Lock()

    def __init__(
        self,
        project_id: str,
        audit_version: int,
        provider: Any,
        *,
        shared_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.project_id = project_id
        self.audit_version = int(audit_version)
        self.provider = provider
        self.shared_context: Dict[str, Any] = shared_context or {}
        self._subsessions: Dict[str, RunnerSubsession] = {}
        self._subsession_lock = threading.Lock()

    @classmethod
    def get_or_create(
        cls,
        project_id: str,
        *,
        audit_version: int,
        provider: Any,
        shared_context: Optional[Dict[str, Any]] = None,
    ) -> "ProjectAuditAgentRunner":
        key = (project_id, int(audit_version))
        with cls._registry_lock:
            runner = cls._registry.get(key)
            if runner is None:
                runner = cls(
                    project_id=project_id,
                    audit_version=audit_version,
                    provider=provider,
                    shared_context=shared_context,
                )
                cls._registry[key] = runner
            elif shared_context:
                runner.shared_context.update(shared_context)
            if provider is not None and runner.provider is None:
                runner.provider = provider
            return runner

    @classmethod
    def clear_registry(cls) -> None:
        with cls._registry_lock:
            cls._registry.clear()

    @classmethod
    def get_existing(
        cls,
        project_id: str,
        *,
        audit_version: int,
    ) -> Optional["ProjectAuditAgentRunner"]:
        with cls._registry_lock:
            return cls._registry.get((project_id, int(audit_version)))

    @classmethod
    def drop(
        cls,
        project_id: str,
        *,
        audit_version: int,
    ) -> None:
        with cls._registry_lock:
            cls._registry.pop((project_id, int(audit_version)), None)

    def resolve_subsession(self, request: RunnerTurnRequest) -> RunnerSubsession:
        slot_key = self._subsession_slot_key(request)
        session_key = self._session_key(request)
        with self._subsession_lock:
            subsession = self._subsessions.get(slot_key)
            if subsession is None:
                subsession = RunnerSubsession(
                    project_id=self.project_id,
                    audit_version=self.audit_version,
                    agent_key=request.agent_key,
                    session_key=session_key,
                    shared_context=self.shared_context,
                )
                self._subsessions[slot_key] = subsession
            return subsession

    def get_existing_subsession(self, agent_key: str) -> Optional[RunnerSubsession]:
        with self._subsession_lock:
            exact = self._subsessions.get(agent_key)
            if exact is not None:
                return exact
            candidates = [
                subsession
                for key, subsession in self._subsessions.items()
                if key == agent_key or key.startswith(f"{agent_key}::")
            ]
        if not candidates:
            return None
        return max(candidates, key=lambda item: float(item.turn_started_at or 0.0))

    def _subsession_slot_key(self, request: RunnerTurnRequest) -> str:
        extra_key = str((request.meta or {}).get("subsession_key") or "").strip()
        if not extra_key:
            return request.agent_key
        return f"{request.agent_key}::{extra_key}"

    def _session_key(self, request: RunnerTurnRequest) -> str:
        extra_key = str((request.meta or {}).get("subsession_key") or "").strip()
        if not extra_key:
            return f"{self.project_id}:{self.audit_version}:{request.agent_key}"
        return f"{self.project_id}:{self.audit_version}:{request.agent_key}:{extra_key}"

    async def _cancel_active_turns_async(self) -> bool:
        cancelled = False
        with self._subsession_lock:
            subsessions = list(self._subsessions.values())

        for subsession in subsessions:
            if str(subsession.current_turn_status or "").lower() != "running":
                continue
            try:
                cancelled = await self.provider.cancel(subsession) or cancelled
            except Exception:
                continue
            subsession.current_turn_status = "cancelled"
            subsession.current_phase = "cancelled"
            subsession.stall_reason = "user_cancelled"
        return cancelled

    def cancel_active_turns(self) -> bool:
        return asyncio.run(self._cancel_active_turns_async())

    def _provider_name(self) -> str:
        provider_name = getattr(self.provider, "provider_name", "")
        return str(provider_name or "unknown").strip() or "unknown"

    def _provider_mode(self) -> str:
        if isinstance(self.shared_context, dict):
            raw = self.shared_context.get("provider_mode")
            if raw:
                return str(raw).strip()
        return self._provider_name()

    def _run_once_timeout_seconds(self) -> float:
        raw = None
        if isinstance(self.shared_context, dict):
            raw = self.shared_context.get("run_once_timeout_seconds")
        if raw is None:
            raw = os.getenv("AUDIT_RUNNER_ONCE_TIMEOUT_SECONDS", "120")
        try:
            value = float(str(raw).strip())
        except (TypeError, ValueError):
            return 120.0
        return max(0.0, value)

    async def _acquire_llm_slot(self, request: RunnerTurnRequest, *, should_cancel=None):  # noqa: ANN001
        gate = get_project_llm_gate(
            project_id=self.project_id,
            audit_version=self.audit_version,
            provider_mode=self._provider_mode(),
            provider_name=self._provider_name(),
            request_has_images=bool(request.images),
        )
        return await gate.acquire(should_cancel=should_cancel)

    async def run_once(
        self,
        request: RunnerTurnRequest,
        *,
        should_cancel=None,  # noqa: ANN001
    ) -> RunnerTurnResult:
        subsession = self.resolve_subsession(request)
        self._ensure_session_started(request, subsession)
        self._mark_turn_started(subsession, phase="running")
        self._set_runner_broadcast(request, subsession, state="progress")
        self._append_event(
            request,
            event_kind="runner_turn_started",
            message=f"{request.agent_name or request.agent_key} 已通过 Runner 发起一次非流式调用",
            meta={
                "turn_kind": request.turn_kind,
                "session_key": subsession.session_key,
                "provider_name": self._provider_name(),
                "provider_mode": self._provider_mode(),
            },
        )
        subsession.current_turn_status = "running"
        timeout_seconds = self._run_once_timeout_seconds()
        try:
            release_llm_slot = await self._acquire_llm_slot(request, should_cancel=should_cancel)
            try:
                if timeout_seconds > 0:
                    result = await asyncio.wait_for(
                        self.provider.run_once(request, subsession),
                        timeout=timeout_seconds,
                    )
                else:
                    result = await self.provider.run_once(request, subsession)
            finally:
                release_llm_slot()
            self._persist_raw_output_artifact(request, subsession, result)
            self._mark_progress(subsession, phase="completed")
            subsession.current_turn_status = "idle"
            subsession.current_phase = "idle"
            return result
        except asyncio.TimeoutError:
            subsession.current_turn_status = "idle"
            subsession.current_phase = "deferred"
            subsession.stall_reason = "once_timeout"
            timeout_message = f"非流式调用超时（>{timeout_seconds:.1f} 秒）"
            self._set_runner_broadcast(request, subsession, state="deferred")
            self._append_event(
                request,
                event_kind="runner_turn_deferred",
                level="warning",
                message=f"{request.agent_name or request.agent_key} 本轮调用超时，Runner 已暂存并继续后续步骤",
                meta={
                    "turn_kind": request.turn_kind,
                    "session_key": subsession.session_key,
                    "provider_name": self._provider_name(),
                    "provider_mode": self._provider_mode(),
                    "reason": "once_timeout",
                    "timeout_seconds": timeout_seconds,
                    "error": timeout_message,
                },
            )
            return RunnerTurnResult(
                provider_name=self._provider_name(),
                output=None,
                status="deferred",
                raw_output="",
                subsession_key=subsession.session_key,
                error=timeout_message,
            )
        except AuditCancellationRequested:
            subsession.current_turn_status = "cancelled"
            subsession.current_phase = "cancelled"
            subsession.stall_reason = "user_cancelled"
            self._append_event(
                request,
                event_kind="runner_turn_cancelled",
                level="warning",
                message=f"{request.agent_name or request.agent_key} 已响应用户中断请求，当前调用已停止",
                meta={
                    "turn_kind": request.turn_kind,
                    "session_key": subsession.session_key,
                    "provider_name": self._provider_name(),
                    "provider_mode": self._provider_mode(),
                    "reason": "user_cancelled",
                },
            )
            raise
        except Exception as exc:
            subsession.current_turn_status = "failed"
            subsession.current_phase = "failed"
            subsession.stall_reason = str(exc)
            self._append_event(
                request,
                event_kind="runner_session_failed",
                level="error",
                message=f"{request.agent_name or request.agent_key} 的 Runner 会话执行失败：{exc}",
                meta={
                    "turn_kind": request.turn_kind,
                    "session_key": subsession.session_key,
                    "provider_name": self._provider_name(),
                    "provider_mode": self._provider_mode(),
                },
            )
            raise

    async def run_stream(
        self,
        request: RunnerTurnRequest,
        *,
        should_cancel=None,  # noqa: ANN001
    ) -> RunnerTurnResult:
        subsession = self.resolve_subsession(request)
        self._ensure_session_started(request, subsession)
        self._mark_turn_started(subsession, phase="running")
        self._set_runner_broadcast(request, subsession, state="progress")
        self._append_event(
            request,
            event_kind="runner_turn_started",
            message=f"{request.agent_name or request.agent_key} 已通过 Runner 发起一次流式调用",
            meta={
                "turn_kind": request.turn_kind,
                "session_key": subsession.session_key,
                "provider_name": self._provider_name(),
                "provider_mode": self._provider_mode(),
            },
        )
        subsession.current_turn_status = "running"

        async def _on_provider_event(event: ProviderStreamEvent) -> None:
            if event.text:
                subsession.output_history.append(event.text)
                subsession.output_history = subsession.output_history[-50:]
                subsession.last_broadcast = event.text
            if event.event_kind == "provider_stream_delta":
                self._mark_progress(subsession, phase="streaming", has_delta=True)
                self._set_runner_broadcast(request, subsession, state="progress", meta=event.meta)
            elif event.event_kind == "phase_event":
                self._mark_progress(
                    subsession,
                    phase=str(event.meta.get("kind") or "progress").strip() or "progress",
                )
                self._set_runner_broadcast(request, subsession, state="progress", meta=event.meta)
            if event.event_kind == "phase_event" and event.meta.get("reason"):
                subsession.retry_count += 1
                subsession.stall_reason = str(event.meta.get("reason") or "").strip() or None
            self._append_event(
                request,
                event_kind=event.event_kind,
                level="warning" if event.event_kind == "phase_event" and event.meta.get("reason") else "info",
                message=event.text or "AI 引擎正在重试",
                meta={
                    "provider_name": self._provider_name(),
                    "provider_mode": self._provider_mode(),
                    **(event.meta or {}),
                },
            )

        while True:
            try:
                release_llm_slot = await self._acquire_llm_slot(request, should_cancel=should_cancel)
                try:
                    result = await self.provider.run_stream(
                        request,
                        subsession,
                        on_event=_on_provider_event,
                        should_cancel=should_cancel,
                    )
                finally:
                    release_llm_slot()
                self._persist_raw_output_artifact(request, subsession, result)
                result = self._apply_output_guard(request, subsession, result)
                self._mark_progress(subsession, phase="completed")
                subsession.current_turn_status = "idle"
                subsession.current_phase = "idle"
                subsession.stall_reason = None
                return result
            except AuditCancellationRequested:
                subsession.current_turn_status = "cancelled"
                subsession.current_phase = "cancelled"
                subsession.stall_reason = "user_cancelled"
                self._set_runner_broadcast(request, subsession, state="cancelled")
                self._append_event(
                    request,
                    event_kind="runner_turn_cancelled",
                    level="warning",
                    message=f"{request.agent_name or request.agent_key} 已响应用户中断请求，当前调用已停止",
                    meta={
                        "turn_kind": request.turn_kind,
                        "session_key": subsession.session_key,
                        "provider_name": self._provider_name(),
                        "provider_mode": self._provider_mode(),
                        "reason": "user_cancelled",
                    },
                )
                raise
            except SdkStreamIdleTimeoutError as exc:
                if self._retry_stalled_turn(request, subsession, exc):
                    continue
                subsession.current_turn_status = "idle"
                subsession.current_phase = "deferred"
                subsession.stall_reason = "idle_timeout"
                self._set_runner_broadcast(request, subsession, state="deferred")
                self._append_event(
                    request,
                    event_kind="runner_turn_deferred",
                    level="warning",
                    message=f"{request.agent_name or request.agent_key} 这一轮长时间没有新进展，Runner 先记下并继续推进后续步骤",
                    meta={
                        "turn_kind": request.turn_kind,
                        "session_key": subsession.session_key,
                        "provider_name": self._provider_name(),
                        "reason": "idle_timeout",
                        "error": str(exc),
                        "repair_attempts": 0,
                    },
                )
                return RunnerTurnResult(
                    provider_name=self._provider_name(),
                    output=None,
                    status="deferred",
                    raw_output="",
                    subsession_key=subsession.session_key,
                    repair_attempts=0,
                    error=str(exc),
                )
            except Exception as exc:
                subsession.current_turn_status = "failed"
                subsession.current_phase = "failed"
                subsession.stall_reason = str(exc)
                self._append_event(
                    request,
                    event_kind="runner_session_failed",
                    level="error",
                    message=f"{request.agent_name or request.agent_key} 的 Runner 会话执行失败：{exc}",
                    meta={
                        "turn_kind": request.turn_kind,
                        "session_key": subsession.session_key,
                        "provider_name": self._provider_name(),
                    },
                )
                raise

    def _ensure_session_started(
        self,
        request: RunnerTurnRequest,
        subsession: RunnerSubsession,
    ) -> None:
        if subsession.session_started:
            self._append_event(
                request,
                event_kind="runner_session_reused",
                message=f"{request.agent_name or request.agent_key} 继续复用已有 Runner 子会话",
                meta={
                    "session_key": subsession.session_key,
                    "provider_name": self._provider_name(),
                },
            )
            return
        subsession.session_started = True
        self._append_event(
            request,
            event_kind="runner_session_started",
            message=f"{request.agent_name or request.agent_key} 已创建项目级 Runner 子会话",
            meta={
                "session_key": subsession.session_key,
                "provider_name": self._provider_name(),
            },
        )

    def _append_event(
        self,
        request: RunnerTurnRequest,
        *,
        event_kind: str,
        message: str,
        level: str = "info",
        meta: Optional[Dict[str, Any]] = None,
        dispatch_observer: bool = True,
    ) -> None:
        from services.audit_runtime.state_transitions import append_run_event

        append_run_event(
            self.project_id,
            self.audit_version,
            level=level,
            step_key=request.step_key or None,
            agent_key=request.agent_key,
            agent_name=request.agent_name or None,
            event_kind=event_kind,
            progress_hint=request.progress_hint,
            message=message,
            meta={
                **(request.meta or {}),
                **(meta or {}),
            },
            dispatch_observer=dispatch_observer,
        )

    def _persist_raw_output_artifact(
        self,
        request: RunnerTurnRequest,
        subsession: RunnerSubsession,
        result: RunnerTurnResult,
    ) -> None:
        raw_output = str(getattr(result, "raw_output", "") or "").strip()
        if not raw_output:
            return

        status = str(getattr(result, "status", "") or "").strip() or "unknown"
        repair_attempts = int(getattr(result, "repair_attempts", 0) or 0)
        error = getattr(result, "error", None)

        artifact_path = save_runner_raw_output(
            project_id=self.project_id,
            audit_version=self.audit_version,
            agent_key=request.agent_key,
            turn_kind=request.turn_kind,
            session_key=subsession.session_key,
            provider_name=self._provider_name(),
            provider_mode=self._provider_mode(),
            status=status,
            raw_output=raw_output,
            meta={
                "agent_name": request.agent_name,
                "step_key": request.step_key,
                "progress_hint": request.progress_hint,
                "repair_attempts": repair_attempts,
                "error": error,
            },
        )
        if artifact_path is None:
            return

        preview = raw_output[:240]
        self._append_event(
            request,
            event_kind="raw_output_saved",
            message=f"{request.agent_name or request.agent_key} 的原始输出已保存，便于后续排查",
            meta={
                "session_key": subsession.session_key,
                "turn_kind": request.turn_kind,
                "provider_name": self._provider_name(),
                "provider_mode": self._provider_mode(),
                "status": status,
                "artifact_path": str(artifact_path),
                "raw_output_chars": len(raw_output),
                "raw_output_preview": preview,
            },
            dispatch_observer=False,
        )

    def _apply_output_guard(
        self,
        request: RunnerTurnRequest,
        subsession: RunnerSubsession,
        result: RunnerTurnResult,
    ) -> RunnerTurnResult:
        if result.output is not None:
            return result

        self._append_event(
            request,
            event_kind="output_validation_failed",
            level="warning",
            message=f"{request.agent_name or request.agent_key} 的输出结构不完整，Runner 正在尝试整理",
            meta={
                "session_key": subsession.session_key,
                "error": result.error,
                "provider_name": self._provider_name(),
            },
        )
        self._append_event(
            request,
            event_kind="output_repair_started",
            message=f"{request.agent_name or request.agent_key} 正在把 AI 引擎的原始输出整理成标准结果",
            meta={
                "session_key": subsession.session_key,
                "provider_name": self._provider_name(),
            },
        )
        self._set_runner_broadcast(request, subsession, state="repairing")

        try:
            repaired_output = guard_output(result.raw_output)
        except Exception as exc:
            result.status = "deferred"
            result.error = str(exc)
            result.repair_attempts += 1
            self._set_runner_broadcast(request, subsession, state="deferred")
            self._append_event(
                request,
                event_kind="runner_turn_deferred",
                level="warning",
                message=f"{request.agent_name or request.agent_key} 仍然没有整理出稳定结果，Runner 先记下并继续推进后续步骤",
                meta={
                    "session_key": subsession.session_key,
                    "error": str(exc),
                    "provider_name": self._provider_name(),
                    "repair_attempts": result.repair_attempts,
                },
            )
            return result

        result.output = repaired_output
        result.status = "ok"
        result.repair_attempts += 1
        self._append_event(
            request,
            event_kind="output_repair_succeeded",
            message=f"{request.agent_name or request.agent_key} 已成功整理出标准结果",
            meta={
                "session_key": subsession.session_key,
                "provider_name": self._provider_name(),
                "repair_attempts": result.repair_attempts,
            },
        )
        return result

    def _mark_turn_started(self, subsession: RunnerSubsession, *, phase: str) -> None:
        now = time.time()
        subsession.turn_started_at = now
        subsession.last_progress_at = now
        subsession.current_phase = phase
        subsession.stall_reason = None

    def _mark_progress(
        self,
        subsession: RunnerSubsession,
        *,
        phase: str,
        has_delta: bool = False,
    ) -> None:
        now = time.time()
        subsession.last_progress_at = now
        subsession.current_phase = phase
        if has_delta:
            subsession.last_delta_at = now

    def _retry_stalled_turn(
        self,
        request: RunnerTurnRequest,
        subsession: RunnerSubsession,
        exc: SdkStreamIdleTimeoutError,
    ) -> bool:
        budget = get_active_visual_budget()
        if budget is None or not budget.consume_retry():
            return False

        subsession.retry_count += 1
        subsession.current_phase = "retrying"
        subsession.stall_reason = "idle_timeout"
        self._set_runner_broadcast(request, subsession, state="retrying")
        self._append_event(
            request,
            event_kind="runner_turn_retrying",
            level="warning",
            message=f"{request.agent_name or request.agent_key} 这一轮长时间没有新进展，Runner 正在重试",
            meta={
                "turn_kind": request.turn_kind,
                "session_key": subsession.session_key,
                "provider_name": self._provider_name(),
                "reason": "idle_timeout",
                "error": str(exc),
                "retry_count": subsession.retry_count,
                "retry_budget_remaining": budget.remaining_retry_budget(),
            },
        )
        return True

    def _set_runner_broadcast(
        self,
        request: RunnerTurnRequest,
        subsession: RunnerSubsession,
        *,
        state: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        message = build_runner_broadcast_message(
            request,
            subsession,
            state=state,
            meta=meta,
        )
        if message == subsession.last_broadcast:
            return message
        subsession.last_broadcast = message
        self._append_event(
            request,
            event_kind="runner_broadcast",
            message=message,
            meta={
                **(request.meta or {}),
                "state": state,
                "turn_kind": request.turn_kind,
                "session_key": subsession.session_key,
                "stream_layer": "user_facing",
                "provider_name": self._provider_name(),
                **(meta or {}),
            },
        )
        return message


__all__ = ["ProjectAuditAgentRunner"]
