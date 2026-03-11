"""Runner 心跳注册表。"""

from __future__ import annotations

import threading
import time
from typing import Dict, Tuple


_lock = threading.Lock()
_heartbeat_registry: Dict[Tuple[str, int], float] = {}


def touch_runner_heartbeat(project_id: str, audit_version: int) -> float:
    now = time.time()
    with _lock:
        _heartbeat_registry[(project_id, int(audit_version))] = now
    return now


def get_runner_heartbeat(project_id: str, audit_version: int) -> float | None:
    with _lock:
        return _heartbeat_registry.get((project_id, int(audit_version)))


def clear_runner_heartbeat(project_id: str, audit_version: int) -> None:
    with _lock:
        _heartbeat_registry.pop((project_id, int(audit_version)), None)


__all__ = [
    "touch_runner_heartbeat",
    "get_runner_heartbeat",
    "clear_runner_heartbeat",
]
