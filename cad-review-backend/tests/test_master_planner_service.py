from __future__ import annotations

import asyncio
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


def test_plan_with_master_llm_ignores_legacy_business_timeout_env(monkeypatch):
    monkeypatch.setenv("AUDIT_MASTER_PLANNER_ENABLED", "1")
    monkeypatch.setenv("AUDIT_MASTER_PLANNER_TIMEOUT_SECONDS", "0.01")
    monkeypatch.setattr(
        master_planner_service,
        "_resolve_master_planner_prompts",
        lambda payload: {"system_prompt": "system", "user_prompt": "user"},
    )

    async def _slow_call_kimi(**kwargs):  # noqa: ANN001
        await asyncio.sleep(0.05)
        return {
            "tasks": [
                {"task_type": "index", "source_sheet_no": "A1.01"},
                {"task_type": "dimension", "source_sheet_no": "A1.01", "target_sheet_no": "A4.01"},
                {"task_type": "material", "source_sheet_no": "A1.01", "target_sheet_no": "A4.01"},
            ]
        }

    monkeypatch.setattr(master_planner_service, "call_kimi", _slow_call_kimi)

    result = master_planner_service.plan_with_master_llm(
        "proj-timeout",
        [_ctx("A1.01"), _ctx("A4.01", indexes=0, sheet_name="节点详图")],
        [_edge("A1.01", "A4.01")],
    )

    assert result["ok"] is True


def test_plan_with_master_llm_sends_only_relevant_contexts(monkeypatch):
    monkeypatch.setenv("AUDIT_MASTER_PLANNER_ENABLED", "1")
    captured_payload = {}

    def _capture_prompts(payload):
        captured_payload.update(payload)
        return {"system_prompt": "system", "user_prompt": "user"}

    async def _fake_call_kimi(**kwargs):  # noqa: ANN001
        return {
            "tasks": [
                {
                    "task_type": "index",
                    "source_sheet_no": "A1.01",
                    "priority": 1,
                },
                {
                    "task_type": "dimension",
                    "source_sheet_no": "A1.01",
                    "target_sheet_no": "A4.01",
                    "priority": 1,
                },
                {
                    "task_type": "material",
                    "source_sheet_no": "A1.01",
                    "target_sheet_no": "A4.01",
                    "priority": 2,
                },
            ]
        }

    monkeypatch.setattr(master_planner_service, "_resolve_master_planner_prompts", _capture_prompts)
    monkeypatch.setattr(master_planner_service, "call_kimi", _fake_call_kimi)

    result = master_planner_service.plan_with_master_llm(
        "proj-relevant",
        [
            _ctx("A1.01", indexes=1),
            _ctx("A4.01", indexes=0, sheet_name="节点详图"),
            _ctx("M9.99", indexes=0, sheet_name="无关说明"),
        ],
        [_edge("A1.01", "A4.01")],
    )

    assert result["ok"] is True
    assert [item["sheet_no"] for item in captured_payload["contexts"]] == ["A1.01", "A4.01"]
