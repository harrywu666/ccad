"""Codex bridge 协议常量和基础类型。"""

from __future__ import annotations

from typing import Any, Literal, TypedDict


BRIDGE_REQUEST_OPS = (
    "start_turn",
    "stream_turn",
    "resume_turn",
    "cancel_turn",
    "close_thread",
)

BRIDGE_RESPONSE_TYPES = (
    "provider_stream_delta",
    "phase_event",
    "error",
    "done",
)

BridgeRequestOp = Literal[
    "start_turn",
    "stream_turn",
    "resume_turn",
    "cancel_turn",
    "close_thread",
]

BridgeResponseType = Literal[
    "provider_stream_delta",
    "phase_event",
    "error",
    "done",
]


class BridgeRequest(TypedDict):
    op: BridgeRequestOp
    request_id: str
    payload: dict[str, Any]


class BridgeResponse(TypedDict):
    type: BridgeResponseType
    request_id: str
    payload: dict[str, Any]


__all__ = [
    "BRIDGE_REQUEST_OPS",
    "BRIDGE_RESPONSE_TYPES",
    "BridgeRequestOp",
    "BridgeResponseType",
    "BridgeRequest",
    "BridgeResponse",
]
