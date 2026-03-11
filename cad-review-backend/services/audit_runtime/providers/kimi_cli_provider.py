"""Kimi CLI Provider 外壳。"""

from __future__ import annotations

import asyncio
import inspect
import json
import shutil
import tempfile
from pathlib import Path
from typing import Optional

from services.audit_runtime.cancel_registry import AuditCancellationRequested
from services.audit_runtime.providers.base import BaseRunnerProvider, StreamCallback
from services.audit_runtime.runner_types import (
    ProviderStreamEvent,
    RunnerSubsession,
    RunnerTurnRequest,
    RunnerTurnResult,
)


class KimiCliProvider(BaseRunnerProvider):
    provider_name = "cli"

    def __init__(self, *, binary: str = "kimi") -> None:
        self.binary = binary

    def is_available(self) -> bool:
        return shutil.which(self.binary) is not None

    def build_command(self, request: RunnerTurnRequest) -> list[str]:
        prompt = self._compose_prompt(request)
        return [
            self.binary,
            "--work-dir",
            str(Path.cwd()),
            "--print",
            "--output-format",
            "stream-json",
            "--prompt",
            prompt,
        ]

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
        if not self.is_available():
            raise RuntimeError(f"Kimi CLI 不可用：未找到命令 {self.binary}")

        temp_dir = self._write_temp_images(request)
        process = await asyncio.create_subprocess_exec(
            *self.build_command(request),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        chunks: list[str] = []
        events: list[ProviderStreamEvent] = []
        buffer = ""

        try:
            while True:
                if should_cancel and should_cancel():
                    process.terminate()
                    raise AuditCancellationRequested("用户手动中断审核")

                data = await process.stdout.read(8192)
                if not data:
                    break
                buffer += data.decode("utf-8", errors="ignore")
                buffer, complete_lines = self._split_complete_lines(buffer)
                for line in complete_lines:
                    for event in self._decode_stream_line(line):
                        events.append(event)
                        if event.event_kind == "provider_stream_delta" and event.text:
                            chunks.append(event.text)
                        if on_event is not None:
                            callback_result = on_event(event)
                            if inspect.isawaitable(callback_result):
                                await callback_result

            if buffer.strip():
                for event in self._decode_stream_line(buffer):
                    events.append(event)
                    if event.event_kind == "provider_stream_delta" and event.text:
                        chunks.append(event.text)
                    if on_event is not None:
                        callback_result = on_event(event)
                        if inspect.isawaitable(callback_result):
                            await callback_result

            returncode = await process.wait()
            if returncode != 0:
                raise RuntimeError(f"Kimi CLI 异常退出，返回码={returncode}")
        finally:
            if process.returncode is None:
                process.terminate()
            if temp_dir:
                shutil.rmtree(temp_dir, ignore_errors=True)

        return RunnerTurnResult(
            provider_name=self.provider_name,
            output=None,
            raw_output="".join(chunks),
            subsession_key=subsession.session_key,
            status="invalid_output",
            events=events,
        )

    def _compose_prompt(self, request: RunnerTurnRequest) -> str:
        system = (request.system_prompt or "").strip()
        user = (request.user_prompt or "").strip()
        image_hint = self._image_hint_block(request)
        task_block = user if not image_hint else f"{user}\n\n{image_hint}"
        if system:
            return f"[系统要求]\n{system}\n\n[用户任务]\n{task_block}"
        return task_block

    def _decode_stream_line(self, line: str) -> list[ProviderStreamEvent]:
        text = (line or "").strip()
        if not text:
            return []
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return [ProviderStreamEvent(event_kind="provider_stream_delta", text=text)]

        event_type = str(payload.get("type") or "").strip().lower()
        if event_type in {"assistant_delta", "delta", "content"}:
            chunk = str(payload.get("text") or payload.get("delta") or payload.get("content") or "")
            if not chunk:
                return []
            return [ProviderStreamEvent(event_kind="provider_stream_delta", text=chunk, meta=payload)]
        if event_type in {"retry", "warning"}:
            return [
                ProviderStreamEvent(
                    event_kind="phase_event",
                    text=str(payload.get("message") or "AI 引擎正在重试"),
                    meta=payload,
                )
            ]
        if event_type in {"done", "complete", "completed"}:
            return []
        if str(payload.get("role") or "").strip().lower() == "assistant":
            return self._decode_assistant_payload(payload)
        return [ProviderStreamEvent(event_kind="phase_event", text=text, meta=payload)]

    def _split_complete_lines(self, buffer: str) -> tuple[str, list[str]]:
        last_newline = max(buffer.rfind("\n"), buffer.rfind("\r"))
        if last_newline < 0:
            return buffer, []
        head = buffer[: last_newline + 1]
        tail = buffer[last_newline + 1 :]
        complete_lines = [part.rstrip("\r\n") for part in head.splitlines()]
        return tail, complete_lines

    def _decode_assistant_payload(self, payload: dict) -> list[ProviderStreamEvent]:
        events: list[ProviderStreamEvent] = []
        content = payload.get("content")
        if not isinstance(content, list):
            return events
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip().lower()
            if item_type == "text":
                chunk = str(item.get("text") or "")
                if chunk:
                    events.append(
                        ProviderStreamEvent(
                            event_kind="provider_stream_delta",
                            text=chunk,
                            meta=item,
                        )
                    )
            elif item_type == "think":
                think = str(item.get("think") or "")
                if think:
                    events.append(
                        ProviderStreamEvent(
                            event_kind="phase_event",
                            text="AI 引擎正在整理这一步的思路",
                            meta={"kind": "think", "raw": think},
                        )
                    )
        return events

    def _write_temp_images(self, request: RunnerTurnRequest) -> str | None:
        if not request.images:
            return None
        base_dir = Path.cwd() / ".artifacts" / "kimi-cli-evidence"
        base_dir.mkdir(parents=True, exist_ok=True)
        temp_dir = tempfile.mkdtemp(prefix="audit-runner-kimi-cli-", dir=str(base_dir))
        request.meta["_cli_image_paths"] = []
        for idx, image in enumerate(request.images, start=1):
            suffix = self._detect_suffix(image)
            path = Path(temp_dir) / f"evidence_{idx}{suffix}"
            path.write_bytes(image)
            request.meta["_cli_image_paths"].append(str(path))
        return temp_dir

    def _image_hint_block(self, request: RunnerTurnRequest) -> str:
        image_paths = request.meta.get("_cli_image_paths") or []
        if not image_paths:
            return ""
        joined = "\n".join(f"- {path}" for path in image_paths)
        return (
            "请先读取这些图片文件，再结合图片回答任务。"
            "\n图片文件路径如下：\n"
            f"{joined}"
        )

    def _detect_suffix(self, image: bytes) -> str:
        header = image[:12]
        if header.startswith(b"\x89PNG"):
            return ".png"
        if header[:3] == b"\xff\xd8\xff":
            return ".jpg"
        if header.startswith(b"GIF8"):
            return ".gif"
        if header.startswith(b"RIFF") and b"WEBP" in image[:16]:
            return ".webp"
        return ".bin"


__all__ = ["KimiCliProvider"]
