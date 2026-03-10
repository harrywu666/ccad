from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_codex_bridge_protocol_supports_start_stream_resume_cancel():
    from services.audit_runtime.codex_bridge_types import (
        BRIDGE_REQUEST_OPS,
        BRIDGE_RESPONSE_TYPES,
    )

    protocol_ops = set(BRIDGE_REQUEST_OPS)
    response_types = set(BRIDGE_RESPONSE_TYPES)

    assert {"start_turn", "stream_turn", "resume_turn", "cancel_turn"} <= protocol_ops
    assert {"provider_stream_delta", "phase_event", "error", "done"} <= response_types
