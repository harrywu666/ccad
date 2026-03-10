"""项目级常驻审图 Runner。"""

from __future__ import annotations

import inspect
import threading
import time
from typing import Any, Dict, Optional, Tuple

from services.audit_runtime.output_guard import guard_output
from services.audit_runtime.runner_types import (
    ProviderStreamEvent,
    RunnerSubsession,
    RunnerTurnRequest,
    RunnerTurnResult,
)


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
            if provider is not None:
                runner.provider = provider
            return runner

    @classmethod
    def clear_registry(cls) -> None:
        with cls._registry_lock:
            cls._registry.clear()

    def resolve_subsession(self, request: RunnerTurnRequest) -> RunnerSubsession:
        with self._subsession_lock:
            subsession = self._subsessions.get(request.agent_key)
            if subsession is None:
                subsession = RunnerSubsession(
                    project_id=self.project_id,
                    audit_version=self.audit_version,
                    agent_key=request.agent_key,
                    session_key=f"{self.project_id}:{self.audit_version}:{request.agent_key}",
                    shared_context=self.shared_context,
                )
                self._subsessions[request.agent_key] = subsession
            return subsession

    def _provider_name(self) -> str:
        provider_name = getattr(self.provider, "provider_name", "")
        return str(provider_name or "unknown").strip() or "unknown"

    async def run_once(
        self,
        request: RunnerTurnRequest,
        *,
        should_cancel=None,  # noqa: ANN001
    ) -> RunnerTurnResult:
        subsession = self.resolve_subsession(request)
        self._ensure_session_started(request, subsession)
        self._mark_turn_started(subsession, phase="running")
        self._append_event(
            request,
            event_kind="runner_turn_started",
            message=f"{request.agent_name or request.agent_key} 已通过 Runner 发起一次非流式调用",
            meta={
                "turn_kind": request.turn_kind,
                "session_key": subsession.session_key,
                "provider_name": self._provider_name(),
            },
        )
        subsession.current_turn_status = "running"
        try:
            result = await self.provider.run_once(request, subsession)
            self._mark_progress(subsession, phase="completed")
            subsession.current_turn_status = "idle"
            subsession.current_phase = "idle"
            return result
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

    async def run_stream(
        self,
        request: RunnerTurnRequest,
        *,
        should_cancel=None,  # noqa: ANN001
    ) -> RunnerTurnResult:
        subsession = self.resolve_subsession(request)
        self._ensure_session_started(request, subsession)
        self._mark_turn_started(subsession, phase="running")
        self._append_event(
            request,
            event_kind="runner_turn_started",
            message=f"{request.agent_name or request.agent_key} 已通过 Runner 发起一次流式调用",
            meta={
                "turn_kind": request.turn_kind,
                "session_key": subsession.session_key,
                "provider_name": self._provider_name(),
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
            elif event.event_kind == "phase_event":
                self._mark_progress(
                    subsession,
                    phase=str(event.meta.get("kind") or "progress").strip() or "progress",
                )
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
                    **(event.meta or {}),
                },
            )

        try:
            result = await self.provider.run_stream(
                request,
                subsession,
                on_event=_on_provider_event,
                should_cancel=should_cancel,
            )
            result = self._apply_output_guard(request, subsession, result)
            self._mark_progress(subsession, phase="completed")
            subsession.current_turn_status = "idle"
            subsession.current_phase = "idle"
            subsession.stall_reason = None
            return result
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
    ) -> None:
        from services.audit_runtime.state_transitions import append_run_event

        subsession = self._subsessions.get(request.agent_key)
        if subsession is not None and message:
            subsession.last_broadcast = message
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
            meta=meta,
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

        try:
            repaired_output = guard_output(result.raw_output)
        except Exception as exc:
            result.status = "needs_review"
            result.error = str(exc)
            result.repair_attempts += 1
            self._append_event(
                request,
                event_kind="runner_turn_needs_review",
                level="warning",
                message=f"{request.agent_name or request.agent_key} 仍然无法整理出稳定结果，已转为待人工确认",
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


__all__ = ["ProjectAuditAgentRunner"]
