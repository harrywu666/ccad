from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_resolve_pipeline_mode_defaults_to_chief_review(monkeypatch):
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")

    monkeypatch.delenv("AUDIT_LEGACY_PIPELINE_ALLOWED", raising=False)
    monkeypatch.delenv("AUDIT_FORCE_PIPELINE_MODE", raising=False)
    monkeypatch.setenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "1")

    assert orchestrator.resolve_pipeline_mode() == "chief_review"


def test_resolve_pipeline_mode_allows_v2_only_with_explicit_legacy_override(monkeypatch):
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")

    monkeypatch.setenv("AUDIT_LEGACY_PIPELINE_ALLOWED", "1")
    monkeypatch.setenv("AUDIT_FORCE_PIPELINE_MODE", "v2")
    monkeypatch.setenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "1")

    assert orchestrator.resolve_pipeline_mode() == "v2"


def test_resolve_pipeline_mode_keeps_chief_review_without_force_even_if_legacy_allowed(monkeypatch):
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")

    monkeypatch.setenv("AUDIT_LEGACY_PIPELINE_ALLOWED", "1")
    monkeypatch.delenv("AUDIT_FORCE_PIPELINE_MODE", raising=False)
    monkeypatch.setenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "1")

    assert orchestrator.resolve_pipeline_mode() == "chief_review"


def test_execute_pipeline_uses_chief_review_when_legacy_not_allowed(monkeypatch):
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")

    monkeypatch.delenv("AUDIT_LEGACY_PIPELINE_ALLOWED", raising=False)
    monkeypatch.setenv("AUDIT_CHIEF_REVIEW_ENABLED", "0")
    monkeypatch.setenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "1")

    captured = {}

    def _capture(impl, *args, **kwargs):  # noqa: ANN001
        captured["impl"] = impl.__name__

    monkeypatch.setattr(orchestrator, "_invoke_pipeline_impl", _capture)

    orchestrator.execute_pipeline(
        "proj-chief-cutover",
        1,
        clear_running=lambda project_id: None,
    )

    assert captured["impl"] == "execute_pipeline_chief_review"
