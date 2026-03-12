from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.llm_request_gate import clear_project_llm_gates
from services.audit_runtime.runner_types import RunnerTurnRequest, RunnerTurnResult


class _FakeProvider:
    provider_name = "api"

    async def run_stream(self, request, subsession, *, on_event=None, should_cancel=None):  # noqa: ANN001
        del request, subsession, on_event, should_cancel
        return RunnerTurnResult(
            provider_name="api",
            output={"ok": True},
            status="ok",
            raw_output='{"ok": true, "source": "model"}',
        )


def test_runner_persists_raw_output_artifact(monkeypatch, tmp_path):
    clear_project_llm_gates()
    monkeypatch.setenv("CCAD_RUNNER_RAW_OUTPUT_DIR", str(tmp_path))
    captured_events: list[dict] = []

    def _fake_append_run_event(project_id, audit_version, **kwargs):  # noqa: ANN001
        captured_events.append(
            {
                "project_id": project_id,
                "audit_version": audit_version,
                **kwargs,
            }
        )

    monkeypatch.setattr(
        "services.audit_runtime.state_transitions.append_run_event",
        _fake_append_run_event,
    )

    runner = ProjectAuditAgentRunner(
        project_id="proj-raw",
        audit_version=7,
        provider=_FakeProvider(),
        shared_context={"provider_mode": "api"},
    )
    request = RunnerTurnRequest(
        agent_key="relationship_review_agent",
        agent_name="关系审查Agent",
        turn_kind="relationship_group_discovery",
        step_key="relationship_discovery",
        system_prompt="system",
        user_prompt="user",
    )

    result = asyncio.run(runner.run_stream(request))

    assert result.output == {"ok": True}
    raw_files = list(tmp_path.glob("*.json"))
    assert len(raw_files) == 1
    payload = json.loads(raw_files[0].read_text(encoding="utf-8"))
    assert payload["project_id"] == "proj-raw"
    assert payload["audit_version"] == 7
    assert payload["agent_key"] == "relationship_review_agent"
    assert payload["provider_name"] == "api"
    assert payload["raw_output"] == '{"ok": true, "source": "model"}'

    saved_events = [item for item in captured_events if item.get("event_kind") == "raw_output_saved"]
    assert len(saved_events) == 1
    assert saved_events[0]["dispatch_observer"] is False
    assert saved_events[0]["meta"]["artifact_path"] == str(raw_files[0])
