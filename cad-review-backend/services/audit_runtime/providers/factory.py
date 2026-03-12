"""Runner Provider 选择器。"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from services.audit_runtime.providers.kimi_api_provider import KimiApiProvider
from services.audit_runtime.providers.kimi_cli_provider import KimiCliProvider
from services.audit_runtime.providers.kimi_sdk_provider import KimiSdkProvider
from services.ai_service import call_kimi as default_call_kimi
from services.ai_service import call_kimi_stream as default_call_kimi_stream


def normalize_provider_mode(raw: Optional[str]) -> str:
    value = str(raw or "").strip().lower()
    aliases = {
        "kimi_api": "api",
        "openrouter": "api",
        "openrouter_api": "api",
        "kimi_cli": "cli",
        "kimi_sdk": "kimi_sdk",
        "codex": "kimi_sdk",
        "codex_sdk": "kimi_sdk",
    }
    normalized = aliases.get(value, value)
    if normalized in {"cli", "api", "sdk", "auto", "kimi_sdk"}:
        return normalized
    return "api"


def _provider_mode(requested_mode: Optional[str] = None) -> str:
    if requested_mode is not None:
        return normalize_provider_mode(requested_mode)
    return normalize_provider_mode(os.getenv("AUDIT_RUNNER_PROVIDER", "api"))


def _has_injected_legacy_funcs(
    *,
    run_once_func,  # noqa: ANN001
    run_stream_func,  # noqa: ANN001
) -> bool:
    if run_once_func is not None and run_once_func is not default_call_kimi:
        return True
    if run_stream_func is not None and run_stream_func is not default_call_kimi_stream:
        return True
    return False


def build_runner_provider(
    *,
    cli_binary: Optional[str] = None,
    requested_mode: Optional[str] = None,
    work_dir: str | Path | None = None,
    run_once_func=None,  # noqa: ANN001
    run_stream_func=None,  # noqa: ANN001
):
    mode = _provider_mode(requested_mode)
    explicit_mode = requested_mode is not None

    cli_provider = KimiCliProvider(binary=cli_binary or os.getenv("KIMI_CLI_BINARY", "kimi"))
    sdk_provider = KimiSdkProvider(work_dir=Path(work_dir).expanduser() if work_dir else None)

    if explicit_mode:
        if mode in {"kimi_sdk", "sdk"}:
            return sdk_provider
        if mode == "cli":
            return cli_provider
        if mode == "api":
            return KimiApiProvider(
                run_once_func=run_once_func,
                run_stream_func=run_stream_func,
            )

    if _has_injected_legacy_funcs(
        run_once_func=run_once_func,
        run_stream_func=run_stream_func,
    ):
        return KimiApiProvider(
            run_once_func=run_once_func,
            run_stream_func=run_stream_func,
        )

    if mode == "kimi_sdk":
        return sdk_provider
    if mode == "sdk":
        return sdk_provider
    if mode == "cli":
        return cli_provider
    if mode == "auto":
        if sdk_provider.is_available():
            return sdk_provider
        if cli_provider.is_available():
            return cli_provider
    if run_once_func is None and run_stream_func is None:
        return KimiApiProvider()
    return KimiApiProvider(
        run_once_func=run_once_func,
        run_stream_func=run_stream_func,
    )


__all__ = ["build_runner_provider", "normalize_provider_mode"]
