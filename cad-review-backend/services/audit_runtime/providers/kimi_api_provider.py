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
from services.kimi_service import call_kimi, call_kimi_stream


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

    async def run_once(
        self,
        request: RunnerTurnRequest,
        subsession: RunnerSubsession,
    ) -> RunnerTurnResult:
        output = await call_kimi(
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
            event = ProviderStreamEvent(
                event_kind="provider_retry",
                text="",
                meta=payload,
            )
            events.append(event)
            await _emit_stream_event(on_event, event)

        output = await call_kimi_stream(
            system_prompt=request.system_prompt,
            user_prompt=request.user_prompt,
            images=request.images,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            on_delta=_on_delta,
            on_retry=_on_retry,
            should_cancel=should_cancel,
        )
        return RunnerTurnResult(
            provider_name=self.provider_name,
            output=output,
            raw_output="".join(chunks),
            subsession_key=subsession.session_key,
            events=events,
        )


__all__ = ["KimiApiProvider"]
