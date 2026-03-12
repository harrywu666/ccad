"""审图流式策略。"""

from __future__ import annotations

import os


_TRUTHY = {"1", "true", "yes", "on"}
_FALSY = {"0", "false", "no", "off"}


def _env_text(name: str) -> str | None:
    raw = os.getenv(name)
    if raw is None:
        return None
    text = str(raw).strip()
    return text or None


def _env_bool(name: str, default: bool) -> bool:
    text = _env_text(name)
    if text is None:
        return default
    lowered = text.lower()
    if lowered in _TRUTHY:
        return True
    if lowered in _FALSY:
        return False
    return default


def resolve_runner_stream_mode() -> str:
    text = _env_text("AUDIT_RUNNER_STREAM_MODE")
    if text:
        lowered = text.lower()
        if lowered in {"once", "stream", "auto"}:
            return lowered
    legacy = _env_text("AUDIT_KIMI_STREAM_ENABLED")
    if legacy is not None:
        return "stream" if legacy.lower() in _TRUTHY else "once"
    return "once"


def audit_stream_enabled(*, default: bool = False) -> bool:
    mode = resolve_runner_stream_mode()
    if mode == "stream":
        return True
    if mode == "once":
        return False
    return default


def user_streaming_enabled() -> bool:
    return _env_bool("AUDIT_USER_STREAMING_ENABLED", False)


def should_expose_event_to_user(event_kind: str) -> bool:
    normalized = str(event_kind or "").strip()
    if normalized not in {"provider_stream_delta", "model_stream_delta"}:
        return True
    return user_streaming_enabled()


__all__ = [
    "audit_stream_enabled",
    "resolve_runner_stream_mode",
    "should_expose_event_to_user",
    "user_streaming_enabled",
]
