"""Python 侧 Codex bridge HTTP client。"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from services.audit_runtime.runner_types import ProviderStreamEvent


@dataclass(slots=True)
class CodexBridgeTurnResult:
    events: list[ProviderStreamEvent] = field(default_factory=list)
    output_text: str = ""
    thread_id: Optional[str] = None
    status: str = "ok"
    done_payload: dict[str, Any] = field(default_factory=dict)


class CodexBridgeClient:
    def __init__(
        self,
        *,
        base_url: Optional[str] = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self.base_url = (
            base_url
            or str(os.getenv("CODEX_BRIDGE_BASE_URL", "http://127.0.0.1:4318")).strip()
        )
        self.timeout_seconds = timeout_seconds

    async def stream_turn(
        self,
        *,
        op: str,
        subsession_key: str,
        input_text: str,
        images: Optional[list[str]] = None,
        thread_id: Optional[str] = None,
        on_event=None,  # noqa: ANN001
    ) -> CodexBridgeTurnResult:
        payload = {
            "op": op,
            "request_id": f"bridge-{uuid.uuid4()}",
            "payload": {
                "subsession_key": subsession_key,
                "input": input_text,
                "images": images or [],
            },
        }
        if thread_id:
            payload["payload"]["thread_id"] = thread_id

        result = CodexBridgeTurnResult()
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            async with client.stream("POST", "/v1/bridge/turn", json=payload) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    item = self._parse_line(line)
                    if item is None:
                        continue
                    event = self._map_event(item)
                    if event is not None:
                        result.events.append(event)
                        if event.event_kind == "provider_stream_delta" and event.text:
                            result.output_text += event.text
                        if on_event:
                            maybe_awaitable = on_event(event)
                            if hasattr(maybe_awaitable, "__await__"):
                                await maybe_awaitable

                    if item.get("type") == "done":
                        done_payload = item.get("payload") or {}
                        result.done_payload = (
                            done_payload if isinstance(done_payload, dict) else {}
                        )
                        result.thread_id = str(result.done_payload.get("thread_id") or "").strip() or None
                        result.status = str(result.done_payload.get("status") or "ok")

        return result

    async def cancel_turn(self, *, subsession_key: str) -> bool:
        payload = {
            "op": "cancel_turn",
            "request_id": f"bridge-{uuid.uuid4()}",
            "payload": {
                "subsession_key": subsession_key,
            },
        }
        async with httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout_seconds) as client:
            response = await client.post("/v1/bridge/turn", json=payload)
            response.raise_for_status()
            data = response.json()
        return bool(data.get("ok"))

    def _parse_line(self, line: str) -> Optional[dict[str, Any]]:
        text = (line or "").strip()
        if not text:
            return None
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None

    def _map_event(self, item: dict[str, Any]) -> Optional[ProviderStreamEvent]:
        event_type = str(item.get("type") or "").strip()
        payload = item.get("payload") if isinstance(item.get("payload"), dict) else {}
        if event_type == "provider_stream_delta":
            return ProviderStreamEvent(
                event_kind="provider_stream_delta",
                text=str(payload.get("text") or ""),
                meta=payload,
            )
        if event_type == "phase_event":
            return ProviderStreamEvent(
                event_kind="phase_event",
                text=str(payload.get("message") or payload.get("kind") or "bridge phase"),
                meta=payload,
            )
        if event_type == "error":
            return ProviderStreamEvent(
                event_kind="error",
                text=str(payload.get("message") or "bridge error"),
                meta=payload,
            )
        return None


__all__ = ["CodexBridgeClient", "CodexBridgeTurnResult"]
