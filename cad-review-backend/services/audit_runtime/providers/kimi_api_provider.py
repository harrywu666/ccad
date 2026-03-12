"""基于现有 Kimi HTTP API 的 Runner Provider。"""

from __future__ import annotations

import inspect
from typing import Optional

from services.audit_runtime.providers.base import BaseRunnerProvider, StreamCallback
from services.audit_runtime.runner_types import (
    ProviderStreamEvent,
    RunnerSubsession,
    RunnerTurnRequest,
    RunnerTurnResult,
)
from services.ai_service import call_kimi, call_kimi_stream


async def _emit_stream_event(
    on_event: Optional[StreamCallback],
    event: ProviderStreamEvent,
) -> None:
    if not on_event:
        return
    result = on_event(event)
    if inspect.isawaitable(result):
        await result


class KimiApiProvider(BaseRunnerProvider):
    provider_name = "api"

    def __init__(self, *, run_once_func=call_kimi, run_stream_func=call_kimi_stream) -> None:  # noqa: ANN001
        self._run_once_func = run_once_func
        self._run_stream_func = run_stream_func

    async def run_once(
        self,
        request: RunnerTurnRequest,
        subsession: RunnerSubsession,
    ) -> RunnerTurnResult:
        output = await self._run_once_func(
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
            images=request.images,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
        )
        return RunnerTurnResult(
            provider_name=self.provider_name,
            output=output,
            subsession_key=subsession.session_key,
        )

    async def run_stream(
        self,
        request: RunnerTurnRequest,
        subsession: RunnerSubsession,
        *,
        on_event: Optional[StreamCallback] = None,
        should_cancel=None,  # noqa: ANN001
    ) -> RunnerTurnResult:
        chunks: list[str] = []
        events: list[ProviderStreamEvent] = []

        async def _on_delta(chunk: str) -> None:
            chunks.append(chunk)
            event = ProviderStreamEvent(
                event_kind="provider_stream_delta",
                text=chunk,
            )
            events.append(event)
            await _emit_stream_event(on_event, event)

        async def _on_retry(payload: dict) -> None:
            attempt = int(payload.get("attempt") or 1)
            event = ProviderStreamEvent(
                event_kind="phase_event",
                text=f"AI 引擎连接暂时被打断，正在第 {attempt} 次重试",
                meta=payload,
            )
            events.append(event)
            await _emit_stream_event(on_event, event)

        try:
            output = await self._run_stream_func(
                system_prompt=request.system_prompt,
                user_prompt=request.user_prompt,
                images=request.images,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                on_delta=_on_delta,
                on_retry=_on_retry,
                should_cancel=should_cancel,
            )
        except Exception as exc:
            if not chunks:
                raise
            return RunnerTurnResult(
                provider_name=self.provider_name,
                output=None,
                status="invalid_output",
                raw_output="".join(chunks),
                subsession_key=subsession.session_key,
                error=str(exc),
                events=events,
            )
        return RunnerTurnResult(
            provider_name=self.provider_name,
            output=output,
            raw_output="".join(chunks),
            subsession_key=subsession.session_key,
            events=events,
        )


__all__ = ["KimiApiProvider"]
