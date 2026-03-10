"""Kimi CLI Provider 外壳。"""

from __future__ import annotations

import shutil
from typing import Optional

from services.audit_runtime.providers.base import BaseRunnerProvider, StreamCallback
from services.audit_runtime.runner_types import RunnerSubsession, RunnerTurnRequest, RunnerTurnResult


class KimiCliProvider(BaseRunnerProvider):
    provider_name = "cli"

    def __init__(self, *, binary: str = "kimi") -> None:
        self.binary = binary

    def is_available(self) -> bool:
        return shutil.which(self.binary) is not None

    async def run_once(
        self,
        request: RunnerTurnRequest,
        subsession: RunnerSubsession,
    ) -> RunnerTurnResult:
        raise NotImplementedError("Kimi CLI Provider 第一版仅提供接口外壳，暂未接入真实执行")

    async def run_stream(
        self,
        request: RunnerTurnRequest,
        subsession: RunnerSubsession,
        *,
        on_event: Optional[StreamCallback] = None,
        should_cancel=None,  # noqa: ANN001
    ) -> RunnerTurnResult:
        raise NotImplementedError("Kimi CLI Provider 第一版仅提供流式接口外壳，暂未接入真实执行")


__all__ = ["KimiCliProvider"]
