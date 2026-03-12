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

from services.audit_runtime.cancel_registry import AuditCancellationRequested
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
        return 45.0
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return 45.0
    return value if value > 0 else 0.0


def _cancel_poll_interval_seconds() -> float:
    raw = os.getenv("AUDIT_SDK_CANCEL_POLL_INTERVAL_SECONDS")
    if raw is None:
        return 0.25
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return 0.25
    return max(0.05, value)


def _sdk_max_concurrency() -> int:
    raw = os.getenv("AUDIT_KIMI_SDK_MAX_CONCURRENCY")
    if raw is None:
        return 6
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return 6
    return max(1, min(30, value))


def _sdk_rate_limit_cooldown_seconds() -> float:
    raw = os.getenv("AUDIT_KIMI_SDK_RATE_LIMIT_COOLDOWN_SECONDS")
    if raw is None:
        return 20.0
    try:
        value = float(str(raw).strip())
    except (TypeError, ValueError):
        return 20.0
    return max(1.0, min(300.0, value))


def _sdk_rate_limit_retry_limit() -> int:
    raw = os.getenv("AUDIT_KIMI_SDK_RATE_LIMIT_RETRY_LIMIT")
    if raw is None:
        return 8
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return 8
    return max(1, min(20, value))


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
    _global_limiters: dict[tuple[int, int], asyncio.Semaphore] = {}
    _global_limiters_lock = threading.Lock()
    _rate_limit_cooldown_until = 0.0
    _rate_limit_cooldown_lock = threading.Lock()

    def __init__(
        self,
        *,
        work_dir: Optional[Path] = None,
        yolo: bool = True,
        session_factory=Session.create,  # noqa: ANN001
    ) -> None:
        self.work_dir = Path(work_dir or Path.cwd()).expanduser()
        self.work_dir.mkdir(parents=True, exist_ok=True)
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
        release_slot = await self._acquire_global_slot(should_cancel=should_cancel)
        try:
            retry_limit = _sdk_rate_limit_retry_limit()
            attempt = 0
            while True:
                await self._wait_for_rate_limit_cooldown(should_cancel=should_cancel)
                try:
                    return await self._run_stream_impl(
                        request,
                        subsession,
                        on_event=on_event,
                        should_cancel=should_cancel,
                    )
                except Exception as exc:
                    if not self._is_rate_limit_error(exc) or attempt >= retry_limit:
                        raise
                    attempt += 1
                    delay = _sdk_rate_limit_cooldown_seconds() * attempt
                    self._extend_rate_limit_cooldown(delay)
                    await _emit_stream_event(
                        on_event,
                        ProviderStreamEvent(
                            event_kind="phase_event",
                            text=f"Kimi Code 当前限流，Runner 将在 {delay:.1f}s 后重试",
                            meta={
                                "reason": "429",
                                "attempt": attempt,
                                "retry_delay_seconds": delay,
                            },
                        ),
                    )
                    await self._sleep_with_cancel(
                        delay,
                        should_cancel=should_cancel,
                    )
        finally:
            release_slot()

    async def _run_stream_impl(
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
        cancel_poll = _cancel_poll_interval_seconds()

        while True:
            next_message = asyncio.create_task(iterator.__anext__())
            try:
                while True:
                    now = time.monotonic()
                    idle_remaining = None
                    if idle_timeout > 0:
                        idle_remaining = max(
                            0.0,
                            idle_timeout - max(0.0, now - last_delta_at),
                        )
                    wait_timeout = cancel_poll
                    if idle_remaining is not None:
                        wait_timeout = min(wait_timeout, max(0.001, idle_remaining))

                    done, _pending = await asyncio.wait(
                        {next_message},
                        timeout=wait_timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if done:
                        msg = next_message.result()
                        break
                    if should_cancel and should_cancel():
                        await _maybe_await(session.cancel())
                        next_message.cancel()
                        await asyncio.gather(next_message, return_exceptions=True)
                        raise AuditCancellationRequested("用户手动中断审核")
                    if idle_timeout > 0 and (time.monotonic() - last_delta_at) >= idle_timeout:
                        await _maybe_await(session.cancel())
                        next_message.cancel()
                        await asyncio.gather(next_message, return_exceptions=True)
                        raise SdkStreamIdleTimeoutError(
                            idle_seconds=idle_timeout,
                            session_key=subsession.session_key,
                        )
            except StopAsyncIteration:
                break

            if should_cancel and should_cancel():
                await _maybe_await(session.cancel())
                raise AuditCancellationRequested("用户手动中断审核")
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

    async def _acquire_global_slot(self, *, should_cancel=None):  # noqa: ANN001
        limiter = self._global_semaphore()
        acquire_task = asyncio.create_task(limiter.acquire())
        acquired = False
        poll_interval = _cancel_poll_interval_seconds()
        try:
            while not acquire_task.done():
                done, _pending = await asyncio.wait(
                    {acquire_task},
                    timeout=poll_interval,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if done:
                    break
                if should_cancel and should_cancel():
                    acquire_task.cancel()
                    await asyncio.gather(acquire_task, return_exceptions=True)
                    raise AuditCancellationRequested("用户手动中断审核")
            await acquire_task
            acquired = True
        except Exception:
            if acquired:
                limiter.release()
            raise

        def _release() -> None:
            limiter.release()

        return _release

    async def _wait_for_rate_limit_cooldown(self, *, should_cancel=None) -> None:  # noqa: ANN001
        while True:
            with self._rate_limit_cooldown_lock:
                remaining = max(0.0, self._rate_limit_cooldown_until - time.monotonic())
            if remaining <= 0:
                return
            await self._sleep_with_cancel(min(remaining, 1.0), should_cancel=should_cancel)

    @classmethod
    def _extend_rate_limit_cooldown(cls, delay_seconds: float) -> None:
        until = time.monotonic() + max(0.0, delay_seconds)
        with cls._rate_limit_cooldown_lock:
            cls._rate_limit_cooldown_until = max(cls._rate_limit_cooldown_until, until)

    async def _sleep_with_cancel(self, delay_seconds: float, *, should_cancel=None) -> None:  # noqa: ANN001
        deadline = time.monotonic() + max(0.0, delay_seconds)
        poll_interval = _cancel_poll_interval_seconds()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            if should_cancel and should_cancel():
                raise AuditCancellationRequested("用户手动中断审核")
            await asyncio.sleep(min(poll_interval, remaining))

    @staticmethod
    def _is_rate_limit_error(exc: Exception) -> bool:
        text = str(exc or "").strip().lower()
        if "rate_limit_reached_error" in text:
            return True
        return "429" in text and "too many requests" in text

    @classmethod
    def _global_semaphore(cls) -> asyncio.Semaphore:
        limit = _sdk_max_concurrency()
        loop = asyncio.get_running_loop()
        key = (id(loop), limit)
        with cls._global_limiters_lock:
            limiter = cls._global_limiters.get(key)
            if limiter is None:
                limiter = asyncio.Semaphore(limit)
                cls._global_limiters[key] = limiter
            return limiter

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

    async def cancel(self, subsession: RunnerSubsession) -> bool:
        key = self._session_store_key(subsession)
        with self._session_lock:
            session = self._sessions.get(key)
        if session is None:
            return False
        await _maybe_await(session.cancel())
        return True

    async def restart_subsession(self, subsession: RunnerSubsession) -> bool:
        key = self._session_store_key(subsession)
        with self._session_lock:
            session = self._sessions.pop(key, None)
        if session is None:
            return False
        try:
            await _maybe_await(session.cancel())
        except Exception:
            pass
        try:
            await _maybe_await(session.close())
        except Exception:
            pass
        return True

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
