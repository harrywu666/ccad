"""项目级常驻审图 Runner。"""

from __future__ import annotations

import threading
from typing import Any, Dict, Optional, Tuple

from services.audit_runtime.runner_types import RunnerSubsession, RunnerTurnRequest


class ProjectAuditAgentRunner:
    """项目级公共 Runner。

    第一版先提供：
    - 单例工厂
    - 项目级共享上下文
    - 按业务 Agent 隔离的子会话池
    """

    _registry: Dict[Tuple[str, int], "ProjectAuditAgentRunner"] = {}
    _registry_lock = threading.Lock()

    def __init__(
        self,
        project_id: str,
        audit_version: int,
        provider: Any,
        *,
        shared_context: Optional[Dict[str, Any]] = None,
    ) -> None:
        self.project_id = project_id
        self.audit_version = int(audit_version)
        self.provider = provider
        self.shared_context: Dict[str, Any] = shared_context or {}
        self._subsessions: Dict[str, RunnerSubsession] = {}
        self._subsession_lock = threading.Lock()

    @classmethod
    def get_or_create(
        cls,
        project_id: str,
        *,
        audit_version: int,
        provider: Any,
        shared_context: Optional[Dict[str, Any]] = None,
    ) -> "ProjectAuditAgentRunner":
        key = (project_id, int(audit_version))
        with cls._registry_lock:
            runner = cls._registry.get(key)
            if runner is None:
                runner = cls(
                    project_id=project_id,
                    audit_version=audit_version,
                    provider=provider,
                    shared_context=shared_context,
                )
                cls._registry[key] = runner
            elif shared_context:
                runner.shared_context.update(shared_context)
            if provider is not None:
                runner.provider = provider
            return runner

    @classmethod
    def clear_registry(cls) -> None:
        with cls._registry_lock:
            cls._registry.clear()

    def resolve_subsession(self, request: RunnerTurnRequest) -> RunnerSubsession:
        with self._subsession_lock:
            subsession = self._subsessions.get(request.agent_key)
            if subsession is None:
                subsession = RunnerSubsession(
                    project_id=self.project_id,
                    audit_version=self.audit_version,
                    agent_key=request.agent_key,
                    session_key=f"{self.project_id}:{self.audit_version}:{request.agent_key}",
                    shared_context=self.shared_context,
                )
                self._subsessions[request.agent_key] = subsession
            return subsession


__all__ = ["ProjectAuditAgentRunner"]
