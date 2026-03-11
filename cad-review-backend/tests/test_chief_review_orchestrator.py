from __future__ import annotations

import importlib
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_execute_pipeline_uses_chief_review_path_when_feature_flag_enabled(monkeypatch):
    orchestrator = importlib.import_module("services.audit_runtime.orchestrator")
    monkeypatch.setenv("AUDIT_CHIEF_REVIEW_ENABLED", "1")
    monkeypatch.setenv("AUDIT_ORCHESTRATOR_V2_ENABLED", "0")

    captured = {}

    def _capture(impl, *args, **kwargs):  # noqa: ANN001
        captured["impl"] = impl.__name__

    monkeypatch.setattr(orchestrator, "_invoke_pipeline_impl", _capture)

    orchestrator.execute_pipeline(
        "proj-chief",
        1,
        clear_running=lambda project_id: None,
    )

    assert captured["impl"] == "execute_pipeline_chief_review"
