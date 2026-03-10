from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = (
        "services.audit.dimension_audit",
        "services.audit_runtime.agent_reports",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit.dimension_audit"):
            sys.modules.pop(name, None)


def _load_module(monkeypatch):
    _clear_backend_modules()
    monkeypatch.setenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "1")
    monkeypatch.setenv("AUDIT_KIMI_STREAM_ENABLED", "1")
    return importlib.import_module("services.audit.dimension_audit")


def test_dimension_agent_builds_report_when_output_is_unstable(monkeypatch):
    dimension_audit = _load_module(monkeypatch)

    report = dimension_audit._build_dimension_agent_report(  # type: ignore[attr-defined]
        {
            "sheet_no": "A1.01",
            "sheet_key": "A101",
        },
        dimension_audit.RunnerTurnResult(
            provider_name="sdk",
            output=None,
            status="deferred",
            raw_output="broken-json",
            repair_attempts=2,
            events=[
                dimension_audit.ProviderStreamEvent(
                    event_kind="output_validation_failed",
                    text="第一次输出不稳",
                )
            ],
        ),
        cleaned=[],
        stage="sheet_semantic",
    )

    assert report.blocking_issues[0]["kind"] == "unstable_output"
    assert report.runner_help_request == "restart_subsession"
    assert report.next_recommended_action == "rerun_current_batch"
    assert report.agent_confidence < 0.5
