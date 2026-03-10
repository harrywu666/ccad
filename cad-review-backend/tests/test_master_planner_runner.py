from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


import services.master_planner_service as master_planner_service
from services.audit_runtime.runner_types import RunnerTurnResult


def _ctx(sheet_no: str, *, indexes: int = 1, sheet_name: str = "平面图"):
    return SimpleNamespace(
        status="ready",
        sheet_no=sheet_no,
        sheet_name=sheet_name,
        meta_json=f'{{"stats": {{"indexes": {indexes}}}}}',
    )


def _edge(source_sheet_no: str, target_sheet_no: str):
    return SimpleNamespace(
        source_sheet_no=source_sheet_no,
        target_sheet_no=target_sheet_no,
        edge_type="index_ref",
        confidence=1.0,
        evidence_json='{"mention_count": 1}',
    )


def test_master_planner_calls_runner_instead_of_direct_kimi(monkeypatch):
    runner_called = {"value": False}

    class _FakeRunner:
        async def run_stream(self, request, *, should_cancel=None):  # noqa: ANN001
            runner_called["value"] = True
            return RunnerTurnResult(
                provider_name="api",
                output={
                    "tasks": [
                        {"task_type": "index", "source_sheet_no": "A1.01"},
                        {"task_type": "dimension", "source_sheet_no": "A1.01", "target_sheet_no": "A4.01"},
                        {"task_type": "material", "source_sheet_no": "A1.01", "target_sheet_no": "A4.01"},
                    ]
                },
            )

    monkeypatch.setenv("AUDIT_MASTER_PLANNER_ENABLED", "1")
    monkeypatch.setenv("AUDIT_KIMI_STREAM_ENABLED", "1")
    monkeypatch.setattr(
        master_planner_service,
        "_resolve_master_planner_prompts",
        lambda payload: {"system_prompt": "system", "user_prompt": "user"},
    )
    monkeypatch.setattr(master_planner_service, "_get_master_runner", lambda *args, **kwargs: _FakeRunner())

    async def _should_not_be_called(**kwargs):  # noqa: ANN001
        raise AssertionError("call_kimi_stream should not be used directly")

    monkeypatch.setattr(master_planner_service, "call_kimi_stream", _should_not_be_called)

    result = master_planner_service.plan_with_master_llm(
        "proj-runner",
        [_ctx("A1.01"), _ctx("A4.01", indexes=0, sheet_name="节点详图")],
        [_edge("A1.01", "A4.01")],
        audit_version=9,
    )

    assert runner_called["value"] is True
    assert result["ok"] is True
