from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _clear_backend_modules() -> None:
    targets = (
        "database",
        "models",
        "services.audit_runtime.state_transitions",
        "services.audit_runtime.runner_observer_session",
    )
    for name in list(sys.modules):
        if name in targets or name.startswith("services.audit_runtime"):
            sys.modules.pop(name, None)


def _load_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("CCAD_DB_PATH", str(tmp_path / "test.sqlite"))
    _clear_backend_modules()

    database = importlib.import_module("database")
    models = importlib.import_module("models")
    state_transitions = importlib.import_module("services.audit_runtime.state_transitions")
    observer_session = importlib.import_module("services.audit_runtime.runner_observer_session")
    observer_types = importlib.import_module("services.audit_runtime.runner_observer_types")
    database.init_db()
    return database.SessionLocal, models, state_transitions, observer_session, observer_types


def test_observer_decision_is_written_to_audit_run_events(monkeypatch, tmp_path):
    session_local, models, state_transitions, observer_session, observer_types = _load_runtime(
        monkeypatch,
        tmp_path,
    )

    db = session_local()
    try:
        db.add(models.Project(id="proj-observer-event", name="Observer Event"))
        db.add(models.AuditRun(project_id="proj-observer-event", audit_version=1, status="running"))
        db.commit()
    finally:
        db.close()

    class _FakeObserverSession:
        async def observe(self, snapshot):  # noqa: ANN001
            return observer_types.RunnerObserverDecision(
                summary="当前像是假活",
                risk_level="high",
                suggested_action="restart_subsession",
                reason="最近长时间没有稳定进展",
                should_intervene=True,
                confidence=0.93,
                user_facing_broadcast="Runner 判断当前步骤像是假活，正在准备介入",
            )

    monkeypatch.setattr(
        observer_session.ProjectRunnerObserverSession,
        "get_or_create",
        classmethod(lambda cls, project_id, *, audit_version, provider=None: _FakeObserverSession()),
    )

    state_transitions.append_run_event(
        "proj-observer-event",
        1,
        step_key="dimension",
        event_kind="runner_turn_retrying",
        message="尺寸审查Agent 这一轮长时间没有新进展，Runner 正在重试",
        meta={"provider_name": "sdk"},
    )

    db = session_local()
    try:
        rows = (
            db.query(models.AuditRunEvent)
            .filter(
                models.AuditRunEvent.project_id == "proj-observer-event",
                models.AuditRunEvent.audit_version == 1,
            )
            .order_by(models.AuditRunEvent.id.asc())
            .all()
        )
    finally:
        db.close()

    event_kinds = [row.event_kind for row in rows]
    assert "runner_observer_decision" in event_kinds
    assert "runner_broadcast" in event_kinds

    observer_row = next(row for row in rows if row.event_kind == "runner_observer_decision")
    payload = json.loads(observer_row.meta_json or "{}")
    assert payload["stream_layer"] == "observer_reasoning"


def test_observer_event_bridge_falls_back_to_event_meta_without_audit_run(monkeypatch, tmp_path):
    session_local, models, state_transitions, observer_session, observer_types = _load_runtime(
        monkeypatch,
        tmp_path,
    )

    db = session_local()
    try:
        db.add(models.Project(id="proj-observer-fallback", name="Observer Fallback"))
        db.commit()
    finally:
        db.close()

    class _FakeObserverSession:
        async def observe(self, snapshot):  # noqa: ANN001
            assert snapshot.runtime_status["provider_mode"] == "sdk"
            return observer_types.RunnerObserverDecision(
                summary="当前像是假活",
                risk_level="high",
                suggested_action="restart_subsession",
                reason="最近长时间没有稳定进展",
                should_intervene=True,
                confidence=0.93,
                user_facing_broadcast="Runner 判断当前步骤像是假活，正在准备介入",
            )

    monkeypatch.setattr(
        observer_session.ProjectRunnerObserverSession,
        "get_or_create",
        classmethod(lambda cls, project_id, *, audit_version, provider=None: _FakeObserverSession()),
    )

    state_transitions.append_run_event(
        "proj-observer-fallback",
        1,
        step_key="dimension",
        event_kind="runner_turn_retrying",
        message="尺寸审查Agent 这一轮长时间没有新进展，Runner 正在重试",
        meta={"provider_name": "sdk", "provider_mode": "sdk"},
    )

    db = session_local()
    try:
        rows = (
            db.query(models.AuditRunEvent)
            .filter(
                models.AuditRunEvent.project_id == "proj-observer-fallback",
                models.AuditRunEvent.audit_version == 1,
            )
            .order_by(models.AuditRunEvent.id.asc())
            .all()
        )
    finally:
        db.close()

    event_kinds = [row.event_kind for row in rows]
    assert "runner_observer_decision" in event_kinds


def test_observer_event_bridge_executes_mark_needs_review_action(monkeypatch, tmp_path):
    session_local, models, state_transitions, observer_session, observer_types = _load_runtime(
        monkeypatch,
        tmp_path,
    )

    db = session_local()
    try:
        db.add(models.Project(id="proj-observer-action", name="Observer Action"))
        db.add(models.AuditRun(project_id="proj-observer-action", audit_version=1, status="running"))
        db.commit()
    finally:
        db.close()

    class _FakeObserverSession:
        async def observe(self, snapshot):  # noqa: ANN001
            return observer_types.RunnerObserverDecision(
                summary="当前步骤已经连续不稳定，应该先转人工确认",
                risk_level="high",
                suggested_action="mark_needs_review",
                reason="连续多次输出不稳定，继续自动推进风险太高",
                should_intervene=True,
                confidence=0.96,
                user_facing_broadcast="Runner 判断当前步骤风险偏高，已转为待人工确认",
            )

    monkeypatch.setattr(
        observer_session.ProjectRunnerObserverSession,
        "get_or_create",
        classmethod(lambda cls, project_id, *, audit_version, provider=None: _FakeObserverSession()),
    )

    state_transitions.append_run_event(
        "proj-observer-action",
        1,
        step_key="dimension",
        event_kind="output_validation_failed",
        message="尺寸审查Agent 的输出结构不完整，Runner 正在尝试整理",
        meta={"provider_name": "sdk", "provider_mode": "sdk"},
    )

    db = session_local()
    try:
        run = (
            db.query(models.AuditRun)
            .filter(
                models.AuditRun.project_id == "proj-observer-action",
                models.AuditRun.audit_version == 1,
            )
            .first()
        )
        rows = (
            db.query(models.AuditRunEvent)
            .filter(
                models.AuditRunEvent.project_id == "proj-observer-action",
                models.AuditRunEvent.audit_version == 1,
            )
            .order_by(models.AuditRunEvent.id.asc())
            .all()
        )
    finally:
        db.close()

    assert run is not None
    assert run.status == "needs_review"
    action_row = next(row for row in rows if row.event_kind == "runner_observer_action")
    payload = json.loads(action_row.meta_json or "{}")
    assert payload["action_name"] == "mark_needs_review"
    assert payload["executed"] is True
