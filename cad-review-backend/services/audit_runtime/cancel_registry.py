"""审核任务取消信号注册表。"""

from __future__ import annotations

import threading


class AuditCancellationRequested(RuntimeError):
    """审核在运行中被用户请求中断。"""


_cancel_lock = threading.Lock()
_cancel_requested_projects: set[str] = set()


def request_cancel(project_id: str) -> None:
    with _cancel_lock:
        _cancel_requested_projects.add(project_id)


def is_cancel_requested(project_id: str) -> bool:
    with _cancel_lock:
        return project_id in _cancel_requested_projects


def clear_cancel_request(project_id: str) -> None:
    with _cancel_lock:
        _cancel_requested_projects.discard(project_id)
