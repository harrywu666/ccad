from __future__ import annotations

import asyncio
import importlib
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.runner_types import (
    ProviderStreamEvent,
    RunnerTurnRequest,
    RunnerTurnResult,
)


def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
        "main",
        "routers.audit",
        "routers.projects",
        "routers.categories",
        "routers.catalog",
        "routers.drawings",
        "routers.dwg",
        "routers.report",
        "routers.settings",
        "routers.feedback",
        "routers.skill_pack",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("routers."):
            sys.modules.pop(name, None)


def _load_test_app(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    main = importlib.import_module("main")
    database.init_db()
    return main.app, database.SessionLocal, models


class _FakeProvider:
    provider_name = "sdk"

    async def run_once(self, request, subsession):  # noqa: ANN001
        return RunnerTurnResult(
            provider_name=self.provider_name,
            output={"ok": True},
            subsession_key=subsession.session_key,
        )

    async def run_stream(self, request, subsession, *, on_event=None, should_cancel=None):  # noqa: ANN001
        if on_event is not None:
            await on_event(
                ProviderStreamEvent(
                    event_kind="provider_stream_delta",
                    text='{"raw":"provider fragment"}',
                    meta={"source": "sdk"},
                )
            )
        return RunnerTurnResult(
            provider_name=self.provider_name,
            output={"ok": True},
            raw_output=json.dumps({"ok": True}, ensure_ascii=False),
            subsession_key=subsession.session_key,
        )


def test_runner_broadcast_is_written_as_user_facing_event(monkeypatch, tmp_path):
    app, session_local, models = _load_test_app(monkeypatch, tmp_path)

    db = session_local()
    try:
        db.add(models.Project(id="proj-runner-broadcast-event", name="Runner Broadcast"))
        db.add(models.AuditRun(project_id="proj-runner-broadcast-event", audit_version=1, status="running"))
        db.commit()
    finally:
        db.close()

    runner = ProjectAuditAgentRunner(
        project_id="proj-runner-broadcast-event",
        audit_version=1,
        provider=_FakeProvider(),
    )
    request = RunnerTurnRequest(
        agent_key="relationship_review_agent",
        agent_name="关系审查Agent",
        step_key="relationship_discovery",
        progress_hint=15,
        turn_kind="relationship_candidate_review",
        system_prompt="sys",
        user_prompt="user",
        meta={"candidate_index": 15, "candidate_total": 24},
    )

    asyncio.run(runner.run_stream(request))

    with TestClient(app) as client:
        response = client.get(
            "/api/projects/proj-runner-broadcast-event/audit/events",
            params={"version": 1},
        )

    assert response.status_code == 200
    payload = response.json()
    broadcast_event = next(
        item for item in payload["items"] if item["event_kind"] == "runner_broadcast"
    )
    assert "正在复核第 15 组候选关系" in broadcast_event["message"]
    assert broadcast_event["meta"]["stream_layer"] == "user_facing"
