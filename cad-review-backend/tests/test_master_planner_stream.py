from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


import services.master_planner_service as master_planner_service


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


def test_plan_with_master_llm_stream_emits_model_delta_events(monkeypatch):
    captured_events: list[dict] = []

    monkeypatch.setenv("AUDIT_MASTER_PLANNER_ENABLED", "1")
    monkeypatch.setenv("AUDIT_KIMI_STREAM_ENABLED", "1")
    monkeypatch.setattr(
        master_planner_service,
        "_resolve_master_planner_prompts",
        lambda payload: {"system_prompt": "system", "user_prompt": "user"},
    )

    async def _fake_call_kimi_stream(**kwargs):  # noqa: ANN001
        await kwargs["on_delta"]('{"tasks":[')
        await kwargs["on_delta"](
            '{"task_type":"index","source_sheet_no":"A1.01"},'
            '{"task_type":"dimension","source_sheet_no":"A1.01","target_sheet_no":"A4.01"},'
            '{"task_type":"material","source_sheet_no":"A1.01","target_sheet_no":"A4.01"}]}'
        )
        return {
            "tasks": [
                {"task_type": "index", "source_sheet_no": "A1.01"},
                {"task_type": "dimension", "source_sheet_no": "A1.01", "target_sheet_no": "A4.01"},
                {"task_type": "material", "source_sheet_no": "A1.01", "target_sheet_no": "A4.01"},
            ]
        }

    monkeypatch.setattr(master_planner_service, "call_kimi_stream", _fake_call_kimi_stream)
    monkeypatch.setattr(
        "services.audit_runtime.state_transitions.append_run_event",
        lambda project_id, audit_version, **kwargs: captured_events.append(kwargs),
    )

    result = master_planner_service.plan_with_master_llm(
        "proj-stream",
        [_ctx("A1.01"), _ctx("A4.01", indexes=0, sheet_name="节点详图")],
        [_edge("A1.01", "A4.01")],
        audit_version=7,
    )

    assert result["ok"] is True
    assert any(event["event_kind"] == "provider_stream_delta" for event in captured_events)
    first_delta = next(event for event in captured_events if event["event_kind"] == "provider_stream_delta")
    assert first_delta["message"] == '{"tasks":['


def test_plan_with_master_llm_stream_emits_retry_events(monkeypatch):
    captured_events: list[dict] = []

    monkeypatch.setenv("AUDIT_MASTER_PLANNER_ENABLED", "1")
    monkeypatch.setenv("AUDIT_KIMI_STREAM_ENABLED", "1")
    monkeypatch.setattr(
        master_planner_service,
        "_resolve_master_planner_prompts",
        lambda payload: {"system_prompt": "system", "user_prompt": "user"},
    )

    async def _fake_call_kimi_stream(**kwargs):  # noqa: ANN001
        await kwargs["on_retry"](
            {
                "attempt": 1,
                "status_code": 429,
                "delay_seconds": 2.0,
                "reason": "retryable_status",
            }
        )
        return {
            "tasks": [
                {"task_type": "index", "source_sheet_no": "A1.01"},
                {"task_type": "dimension", "source_sheet_no": "A1.01", "target_sheet_no": "A4.01"},
                {"task_type": "material", "source_sheet_no": "A1.01", "target_sheet_no": "A4.01"},
            ]
        }

    monkeypatch.setattr(master_planner_service, "call_kimi_stream", _fake_call_kimi_stream)
    monkeypatch.setattr(
        "services.audit_runtime.state_transitions.append_run_event",
        lambda project_id, audit_version, **kwargs: captured_events.append(kwargs),
    )

    result = master_planner_service.plan_with_master_llm(
        "proj-stream",
        [_ctx("A1.01"), _ctx("A4.01", indexes=0, sheet_name="节点详图")],
        [_edge("A1.01", "A4.01")],
        audit_version=8,
    )

    assert result["ok"] is True
    assert any(event["event_kind"] == "phase_event" for event in captured_events)
    assert "第 1 次重试" in captured_events[-1]["message"]
