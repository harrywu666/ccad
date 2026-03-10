"""Runner Provider 基类。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Awaitable, Callable, Optional

from services.audit_runtime.runner_types import (
    ProviderStreamEvent,
    RunnerSubsession,
    RunnerTurnRequest,
    RunnerTurnResult,
)
from services.audit_runtime.runner_observer_types import (
    RunnerObserverDecision,
    RunnerObserverFeedSnapshot,
    RunnerObserverMemory,
)


StreamCallback = Callable[[ProviderStreamEvent], Optional[Awaitable[None]]]


class BaseRunnerProvider(ABC):
    provider_name: str = "base"

    @abstractmethod
    async def run_once(
        self,
        request: RunnerTurnRequest,
        subsession: RunnerSubsession,
    ) -> RunnerTurnResult: ...

    @abstractmethod
    async def run_stream(
        self,
        request: RunnerTurnRequest,
        subsession: RunnerSubsession,
        *,
        on_event: Optional[StreamCallback] = None,
        should_cancel=None,  # noqa: ANN001
    ) -> RunnerTurnResult: ...

    async def cancel(self, subsession: RunnerSubsession) -> bool:
        return False

    async def restart_subsession(self, subsession: RunnerSubsession) -> bool:
        return False

    async def observe_once(
        self,
        snapshot: RunnerObserverFeedSnapshot,
        memory: RunnerObserverMemory,
    ) -> RunnerObserverDecision:
        raise NotImplementedError("observe_once is not implemented for this provider")


__all__ = ["BaseRunnerProvider", "StreamCallback"]
