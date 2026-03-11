from __future__ import annotations

import time
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.runner_heartbeat import (  # type: ignore[attr-defined]
    clear_runner_heartbeat,
    get_runner_heartbeat,
    touch_runner_heartbeat,
)


def test_runner_heartbeat_updates_timestamp():
    clear_runner_heartbeat("proj-heartbeat", 2)
    first = touch_runner_heartbeat("proj-heartbeat", 2)
    time.sleep(0.01)
    second = touch_runner_heartbeat("proj-heartbeat", 2)

    assert second >= first
    assert get_runner_heartbeat("proj-heartbeat", 2) == second

