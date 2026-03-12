from __future__ import annotations

import importlib


def test_stream_policy_defaults_to_once(monkeypatch):
    monkeypatch.delenv("AUDIT_RUNNER_STREAM_MODE", raising=False)
    monkeypatch.delenv("AUDIT_KIMI_STREAM_ENABLED", raising=False)
    policy = importlib.import_module("services.audit_runtime.stream_policy")
    importlib.reload(policy)

    assert policy.resolve_runner_stream_mode() == "once"
    assert policy.audit_stream_enabled(default=False) is False


def test_stream_policy_respects_legacy_flag(monkeypatch):
    monkeypatch.delenv("AUDIT_RUNNER_STREAM_MODE", raising=False)
    monkeypatch.setenv("AUDIT_KIMI_STREAM_ENABLED", "1")
    policy = importlib.import_module("services.audit_runtime.stream_policy")
    importlib.reload(policy)

    assert policy.resolve_runner_stream_mode() == "stream"
    assert policy.audit_stream_enabled(default=False) is True


def test_user_stream_events_hidden_by_default(monkeypatch):
    monkeypatch.delenv("AUDIT_USER_STREAMING_ENABLED", raising=False)
    policy = importlib.import_module("services.audit_runtime.stream_policy")
    importlib.reload(policy)

    assert policy.should_expose_event_to_user("provider_stream_delta") is False
    assert policy.should_expose_event_to_user("phase_completed") is True
