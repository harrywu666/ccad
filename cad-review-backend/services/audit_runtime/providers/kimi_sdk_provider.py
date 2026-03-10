"""基于 kimi-agent-sdk 的 Runner Provider。"""

from __future__ import annotations

import asyncio
import base64
import inspect
import os
import threading
import time
from pathlib import Path
from typing import Optional

from kaos.path import KaosPath
from kimi_agent_sdk import ApprovalRequest, ImageURLPart, Session, TextPart, ThinkPart

from services.audit_runtime.providers.base import BaseRunnerProvider, StreamCallback
from services.audit_runtime.runner_observer_prompt import (
    build_runner_observer_system_prompt,
    build_runner_observer_user_prompt,
)
from services.audit_runtime.runner_types import (
    ProviderStreamEvent,
    RunnerSubsession,
    RunnerTurnRequest,
    RunnerTurnResult,
)
from services.audit_runtime.runner_observer_types import (
    RunnerObserverFeedSnapshot,
    RunnerObserverMemory,
    observer_decision_from_text,
)


async def _emit_stream_event(
    on_event: Optional[StreamCallback],
    event: ProviderStreamEvent,
) -> None:
    if not on_event:
        return
    result = on_event(event)
    if inspect.isawaitable(result):
        await result


async def _maybe_await(result) -> None:  # noqa: ANN001
    if inspect.isawaitable(result):
        await result


def _idle_timeout_seconds() -> float:
    raw = os.getenv("AUDIT_SDK_STREAM_IDLE_TIMEOUT_SECONDS")
    if raw is None:
        return 0.0
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return 0.0
    return value if value > 0 else 0.0


class SdkStreamIdleTimeoutError(RuntimeError):
    """SDK 流式输出长时间没有新正文时抛出的异常。"""

    def __init__(self, *, idle_seconds: float, session_key: str) -> None:
        super().__init__(
            f"sdk stream idle timeout after {idle_seconds:.2f}s for session {session_key}"
        )
        self.idle_seconds = idle_seconds
        self.session_key = session_key


class KimiSdkProvider(BaseRunnerProvider):
    provider_name = "sdk"

    def __init__(
        self,
        *,
        work_dir: Optional[Path] = None,
        yolo: bool = True,
        session_factory=Session.create,  # noqa: ANN001
    ) -> None:
        self.work_dir = Path(work_dir or Path.cwd())
        self.yolo = yolo
        self._session_factory = session_factory
        self._sessions = {}
        self._session_lock = threading.Lock()

    def is_available(self) -> bool:
        return True

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
        chunks: list[str] = []
        thinks: list[str] = []
        prompt_input = self._build_user_input(request)
        session = await self._get_or_create_session(subsession)
        idle_timeout = _idle_timeout_seconds()
        last_delta_at = time.monotonic()
        stream = session.prompt(prompt_input, merge_wire_messages=True)
        iterator = stream.__aiter__()

        while True:
            next_message = iterator.__anext__()
            try:
                if idle_timeout > 0:
                    timeout_seconds = max(
                        0.001,
                        idle_timeout - max(0.0, time.monotonic() - last_delta_at),
                    )
                    msg = await asyncio.wait_for(next_message, timeout=timeout_seconds)
                else:
                    msg = await next_message
            except StopAsyncIteration:
                break
            except asyncio.TimeoutError as exc:
                await _maybe_await(session.cancel())
                raise SdkStreamIdleTimeoutError(
                    idle_seconds=idle_timeout,
                    session_key=subsession.session_key,
                ) from exc

            if should_cancel and should_cancel():
                await _maybe_await(session.cancel())
                raise RuntimeError("用户手动中断审核")
            if self._is_think_part(msg):
                think = getattr(msg, "think", "")
                if think:
                    thinks.append(think)
                    await _emit_stream_event(
                        on_event,
                        ProviderStreamEvent(
                            event_kind="phase_event",
                            text="AI 引擎正在整理这一步的思路",
                            meta={"kind": "think", "raw": think},
                        ),
                    )
                continue
            if self._is_text_part(msg):
                text = getattr(msg, "text", "")
                if text:
                    last_delta_at = time.monotonic()
                    chunks.append(text)
                    await _emit_stream_event(
                        on_event,
                        ProviderStreamEvent(
                            event_kind="provider_stream_delta",
                            text=text,
                        ),
                    )
                continue
            if self._is_approval_request(msg):
                msg.resolve("approve")
                await _emit_stream_event(
                    on_event,
                    ProviderStreamEvent(
                        event_kind="phase_event",
                        text="AI 引擎正在请求执行权限，Runner 已自动批准",
                        meta={
                            "kind": "approval",
                            "action": getattr(msg, "action", ""),
                            "description": getattr(msg, "description", ""),
                        },
                    ),
                )
                continue

        raw_output = "".join(chunks)
        return RunnerTurnResult(
            provider_name=self.provider_name,
            output=None,
            raw_output=raw_output,
            subsession_key=subsession.session_key,
            status="invalid_output",
            events=[
                ProviderStreamEvent(event_kind="provider_stream_delta", text=raw_output)
            ]
            if raw_output
            else [],
        )

    async def observe_once(
        self,
        snapshot: RunnerObserverFeedSnapshot,
        memory: RunnerObserverMemory,
    ):
        session = await self._get_or_create_observer_session(memory)
        prompt_input = self._build_observer_input(snapshot, memory)
        chunks: list[str] = []
        stream = session.prompt(prompt_input, merge_wire_messages=True)
        async for msg in stream:
            if self._is_text_part(msg):
                text = getattr(msg, "text", "")
                if text:
                    chunks.append(text)
        return observer_decision_from_text("".join(chunks))

    def _session_store_key(self, subsession: RunnerSubsession) -> str:
        return subsession.session_key

    async def _get_or_create_session(self, subsession: RunnerSubsession):
        key = self._session_store_key(subsession)
        with self._session_lock:
            session = self._sessions.get(key)
        if session is not None:
            return session

        session = await self._session_factory(
            work_dir=KaosPath.unsafe_from_local_path(self.work_dir),
            yolo=self.yolo,
        )
        with self._session_lock:
            existing = self._sessions.get(key)
            if existing is not None:
                try:
                    await session.close()
                except Exception:
                    pass
                return existing
            self._sessions[key] = session
        return session

    async def _get_or_create_observer_session(self, memory: RunnerObserverMemory):
        key = f"observer:{memory.project_id}:{memory.audit_version}"
        with self._session_lock:
            session = self._sessions.get(key)
        if session is not None:
            return session

        session = await self._session_factory(
            work_dir=KaosPath.unsafe_from_local_path(self.work_dir),
            yolo=self.yolo,
        )
        with self._session_lock:
            existing = self._sessions.get(key)
            if existing is not None:
                try:
                    await session.close()
                except Exception:
                    pass
                return existing
            self._sessions[key] = session
        return session

    def _build_user_input(self, request: RunnerTurnRequest):
        system = (request.system_prompt or "").strip()
        user = (request.user_prompt or "").strip()
        task = f"[系统要求]\n{system}\n\n[用户任务]\n{user}" if system else user
        if not request.images:
            return task
        parts = [TextPart(text=task)]
        for image in request.images:
            parts.append(
                ImageURLPart(
                    image_url=ImageURLPart.ImageURL(
                        url=self._to_data_url(image),
                    )
                )
            )
        return parts

    def _build_observer_input(
        self,
        snapshot: RunnerObserverFeedSnapshot,
        memory: RunnerObserverMemory,
    ) -> str:
        system = build_runner_observer_system_prompt()
        user = build_runner_observer_user_prompt(snapshot, memory)
        return f"[系统要求]\n{system}\n\n[用户任务]\n{user}"

    def _to_data_url(self, image: bytes) -> str:
        mime = self._detect_mime(image)
        encoded = base64.b64encode(image).decode("utf-8")
        return f"data:{mime};base64,{encoded}"

    def _detect_mime(self, image: bytes) -> str:
        header = image[:12]
        if header.startswith(b"\x89PNG"):
            return "image/png"
        if header[:3] == b"\xff\xd8\xff":
            return "image/jpeg"
        if header.startswith(b"GIF8"):
            return "image/gif"
        if header.startswith(b"RIFF") and b"WEBP" in image[:16]:
            return "image/webp"
        return "application/octet-stream"

    def _is_text_part(self, msg) -> bool:  # noqa: ANN001
        return isinstance(msg, TextPart) or (
            hasattr(msg, "text") and msg.__class__.__name__.lower().endswith("text")
        )

    def _is_think_part(self, msg) -> bool:  # noqa: ANN001
        return isinstance(msg, ThinkPart) or (
            hasattr(msg, "think") and msg.__class__.__name__.lower().endswith("think")
        )

    def _is_approval_request(self, msg) -> bool:  # noqa: ANN001
        return isinstance(msg, ApprovalRequest) or (
            hasattr(msg, "resolve")
            and hasattr(msg, "action")
            and hasattr(msg, "description")
        )


__all__ = ["KimiSdkProvider", "SdkStreamIdleTimeoutError"]
