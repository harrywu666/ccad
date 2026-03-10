"""Runner Observer Agent 的动作闸门。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Dict


@dataclass(slots=True)
class RunnerActionCheck:
    allowed: bool
    action_name: str
    reason: str = ""


class RunnerActionGate:
    """只允许 Runner 执行白名单动作。"""

    _ALLOWED_ACTIONS = {
        "observe_only",
        "broadcast_update",
        "cancel_turn",
        "restart_subsession",
        "rerun_current_step",
        "mark_needs_review",
    }

    def __init__(self, *, project_root: str) -> None:
        self.project_root = project_root

    def check_allowed(self, action_name: str) -> RunnerActionCheck:
        normalized = str(action_name or "").strip()
        if normalized in self._ALLOWED_ACTIONS:
            return RunnerActionCheck(allowed=True, action_name=normalized)
        return RunnerActionCheck(
            allowed=False,
            action_name=normalized,
            reason="action_not_allowed",
        )

    def _resolve_callback(
        self,
        action_name: str,
        context: Dict[str, Any],
    ) -> Callable[[], Any] | None:
        callback = context.get(action_name)
        if callable(callback):
            return callback
        return None

    def execute(self, action_name: str, *, context: Dict[str, Any] | None = None) -> Dict[str, Any]:
        check = self.check_allowed(action_name)
        payload = {
            "allowed": check.allowed,
            "action_name": check.action_name,
            "reason": check.reason,
            "context": dict(context or {}),
            "executed": False,
            "result": None,
        }
        if not check.allowed:
            return payload

        runtime_context = dict(context or {})
        callback = self._resolve_callback(check.action_name, runtime_context)
        if callback is not None:
            payload["result"] = callback()
            payload["executed"] = True
            payload["reason"] = ""
            return payload

        if check.action_name in {"observe_only", "broadcast_update"}:
            payload["executed"] = True
            payload["result"] = runtime_context.get("broadcast_message") or check.action_name
            payload["reason"] = ""
            return payload

        payload["reason"] = "action_callback_missing"
        return {
            **payload,
        }


__all__ = ["RunnerActionCheck", "RunnerActionGate"]
