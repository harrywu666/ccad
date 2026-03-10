"""通过 Node bridge 接 Codex SDK 的 Runner Provider。"""

from __future__ import annotations

from typing import Optional

from services.audit_runtime.codex_bridge_client import CodexBridgeClient
from services.audit_runtime.runner_observer_prompt import (
    build_runner_observer_system_prompt,
    build_runner_observer_user_prompt,
)
from services.audit_runtime.providers.base import BaseRunnerProvider, StreamCallback
from services.audit_runtime.runner_observer_types import (
    RunnerObserverFeedSnapshot,
    RunnerObserverMemory,
    observer_decision_from_text,
)
from services.audit_runtime.runner_types import (
    RunnerSubsession,
    RunnerTurnRequest,
    RunnerTurnResult,
)

CODEX_BRIDGE_BOUNDARY = True


def _thread_map(subsession: RunnerSubsession) -> dict[str, str]:
    mapping = subsession.shared_context.setdefault("__codex_thread_map__", {})
    if not isinstance(mapping, dict):
        mapping = {}
        subsession.shared_context["__codex_thread_map__"] = mapping
    return mapping


class CodexSdkProvider(BaseRunnerProvider):
    provider_name = "codex_sdk"

    def __init__(self, *, bridge_client: Optional[CodexBridgeClient] = None) -> None:
        self.bridge_client = bridge_client or CodexBridgeClient()
        self._observer_threads: dict[str, str] = {}

    async def run_once(
        self,
        request: RunnerTurnRequest,
        subsession: RunnerSubsession,
    ) -> RunnerTurnResult:
        return await self.run_stream(request, subsession)

    async def run_stream(
        self,
        request: RunnerTurnRequest,
        subsession: RunnerSubsession,
        *,
        on_event: Optional[StreamCallback] = None,
        should_cancel=None,  # noqa: ANN001
    ) -> RunnerTurnResult:
        if should_cancel and should_cancel():
            await self.cancel(subsession)
            raise RuntimeError("用户手动中断审核")

        thread_id = _thread_map(subsession).get(subsession.session_key)
        op = "resume_turn" if thread_id else "start_turn"
        bridge_result = await self.bridge_client.stream_turn(
            op=op,
            subsession_key=subsession.session_key,
            thread_id=thread_id,
            input_text=self._build_prompt(request),
            on_event=on_event,
        )

        if bridge_result.thread_id:
            _thread_map(subsession)[subsession.session_key] = bridge_result.thread_id

        return RunnerTurnResult(
            provider_name=self.provider_name,
            output=None,
            status="invalid_output",
            raw_output=bridge_result.output_text,
            subsession_key=subsession.session_key,
            error=None if bridge_result.status == "ok" else bridge_result.status,
            events=bridge_result.events,
        )

    async def cancel(self, subsession: RunnerSubsession) -> bool:
        return await self.bridge_client.cancel_turn(subsession_key=subsession.session_key)

    async def restart_subsession(self, subsession: RunnerSubsession) -> bool:
        cancelled = await self.cancel(subsession)
        thread_id = _thread_map(subsession).pop(subsession.session_key, None)
        return cancelled or thread_id is not None

    async def observe_once(
        self,
        snapshot: RunnerObserverFeedSnapshot,
        memory: RunnerObserverMemory,
    ):
        subsession_key = f"observer:{memory.project_id}:{memory.audit_version}"
        thread_id = self._observer_threads.get(subsession_key)
        op = "resume_turn" if thread_id else "start_turn"
        bridge_result = await self.bridge_client.stream_turn(
            op=op,
            subsession_key=subsession_key,
            thread_id=thread_id,
            input_text=self._build_observer_prompt(snapshot, memory),
        )
        if bridge_result.thread_id:
            self._observer_threads[subsession_key] = bridge_result.thread_id
        return observer_decision_from_text(bridge_result.output_text)

    def _build_prompt(self, request: RunnerTurnRequest) -> str:
        system = (request.system_prompt or "").strip()
        user = (request.user_prompt or "").strip()
        if system and user:
            return f"[系统要求]\n{system}\n\n[用户任务]\n{user}"
        return user or system

    def _build_observer_prompt(
        self,
        snapshot: RunnerObserverFeedSnapshot,
        memory: RunnerObserverMemory,
    ) -> str:
        system = build_runner_observer_system_prompt()
        user = build_runner_observer_user_prompt(snapshot, memory)
        return f"[系统要求]\n{system}\n\n[用户任务]\n{user}"

__all__ = ["CODEX_BRIDGE_BOUNDARY", "CodexSdkProvider"]
