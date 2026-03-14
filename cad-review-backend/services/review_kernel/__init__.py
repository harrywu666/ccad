"""数据驱动审图内核。"""

from __future__ import annotations

from typing import Any


def execute_pipeline(*args: Any, **kwargs: Any) -> None:
    from .orchestrator import execute_pipeline as _execute_pipeline

    _execute_pipeline(*args, **kwargs)


def resolve_pipeline_mode() -> str:
    from .orchestrator import resolve_pipeline_mode as _resolve_pipeline_mode

    return _resolve_pipeline_mode()

__all__ = ["execute_pipeline", "resolve_pipeline_mode"]
