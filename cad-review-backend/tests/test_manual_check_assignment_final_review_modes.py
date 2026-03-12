from __future__ import annotations

import os
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from utils.manual_check_ai_review_flow import (
    _build_runtime_watch_line,
    _is_terminal_audit_status,
    _load_local_env_file,
    _local_provider_env_overrides,
    _provider_preflight,
    _resolve_runtime_deadline,
    _run_mode_env,
    build_assignment_final_review_summary,
    resolve_run_modes,
)


def test_manual_check_supports_assignment_final_review_mode():
    assert resolve_run_modes("assignment_final_review") == ["assignment_final_review"]


def test_assignment_final_review_mode_uses_chief_review_runtime_switches():
    env = _run_mode_env("assignment_final_review")

    assert env["AUDIT_CHIEF_REVIEW_ENABLED"] == "1"
    assert env["AUDIT_LEGACY_PIPELINE_ALLOWED"] == "0"
    assert env["AUDIT_FORCE_PIPELINE_MODE"] is None


def test_assignment_final_review_summary_exposes_acceptance_signals():
    summary = build_assignment_final_review_summary(
        {
            "status": {
                "pipeline_mode": "chief_review",
                "ui_runtime": {
                    "worker_sessions": [
                        {"session_key": "assignment:asg-1"},
                        {"session_key": "assignment:asg-2"},
                    ],
                    "final_review": {"current_action": "终审正在复核 asg-2"},
                    "organizer": {"current_action": "正在整理终审通过的问题"},
                },
            },
            "runtime_tasks": [
                {"task_type": "dimension"},
                {"task_type": "index"},
            ],
            "runtime_results": [
                {
                    "finding_status": "confirmed",
                    "evidence_json": '{"finding":{"anchors":[{"sheet_no":"A1.01","global_pct":{"x":42.1,"y":61.2}}]}}',
                }
            ],
            "runtime_events": [],
            "runtime_report": {
                "mode": "marked",
                "anchors_json_path": "/tmp/report_v3_anchors.json",
            },
            "organizer_markdown_available": True,
        }
    )

    assert summary["pipeline_mode"] == "assignment_final_review"
    assert summary["visible_worker_card_count"] == 2
    assert summary["assignment_count"] == 2
    assert summary["final_review_visible"] is True
    assert summary["organizer_markdown_output"] is True
    assert summary["marked_report_generated"] is True
    assert summary["grounded_final_issue_count"] == 1


def test_assignment_final_review_summary_falls_back_to_chief_assignment_count():
    summary = build_assignment_final_review_summary(
        {
            "status": {
                "current_step": "标高一致性 Skill 执行复核",
                "ui_runtime": {
                    "chief": {"assigned_task_count": 15},
                    "worker_sessions": [{"session_key": f"legacy:{idx}"} for idx in range(5)],
                },
            },
            "runtime_tasks": [],
            "runtime_results": [],
            "runtime_events": [],
            "runtime_report": {},
            "organizer_markdown_available": False,
        }
    )

    assert summary["assignment_count"] == 15
    assert summary["worker_card_not_exceed_assignment_count"] is True
    assert summary["final_review_visible"] is False


def test_local_provider_env_overrides_follow_requested_provider_mode():
    assert _local_provider_env_overrides("openrouter") == {"KIMI_PROVIDER": "openrouter"}
    assert _local_provider_env_overrides("api") == {"KIMI_PROVIDER": "official"}


def test_provider_preflight_requires_matching_env(monkeypatch):
    monkeypatch.delenv("KIMI_OFFICIAL_API_KEY", raising=False)
    monkeypatch.delenv("MOONSHOT_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    official = _provider_preflight("api")
    openrouter = _provider_preflight("openrouter")

    assert official["ok"] is False
    assert official["missing_env"] == ["KIMI_OFFICIAL_API_KEY", "MOONSHOT_API_KEY"]
    assert openrouter["ok"] is False
    assert openrouter["missing_env"] == ["OPENROUTER_API_KEY"]


def test_load_local_env_file_populates_missing_env(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    backend_dir = tmp_path / "backend"
    backend_dir.mkdir()
    (backend_dir / ".env").write_text("OPENROUTER_API_KEY=test-openrouter-key\n", encoding="utf-8")

    _load_local_env_file(backend_dir)

    assert os.environ["OPENROUTER_API_KEY"] == "test-openrouter-key"


def test_assignment_final_review_summary_exposes_provider_blocker():
    summary = build_assignment_final_review_summary(
        {
            "status": {
                "pipeline_mode": "chief_review",
                "ui_runtime": {
                    "chief": {"assigned_task_count": 1},
                    "worker_sessions": [{"session_key": "assignment:asg-1"}],
                },
            },
            "runtime_tasks": [],
            "runtime_results": [],
            "runtime_events": [
                {
                    "event_kind": "runner_session_failed",
                    "message": "尺寸一致性 Skill 的 Runner 会话执行失败：未设置 KIMI_OFFICIAL_API_KEY 或 MOONSHOT_API_KEY 环境变量",
                }
            ],
            "runtime_report": {},
            "organizer_markdown_available": False,
            "provider_preflight": {
                "ok": False,
                "detail": "缺少 provider 环境变量：KIMI_OFFICIAL_API_KEY / MOONSHOT_API_KEY。",
            },
        }
    )

    assert summary["provider_preflight_ok"] is False
    assert summary["blocking_reason"] == "missing_provider_env"
    assert summary["failed_runner_event_count"] == 1
    assert "KIMI_OFFICIAL_API_KEY" in str(summary["last_failure_message"])


def test_resolve_runtime_deadline_supports_unbounded_wait():
    assert _resolve_runtime_deadline(wait_seconds=30, wait_until_finished=True, max_wait_seconds=None) is None


def test_resolve_runtime_deadline_uses_fixed_window_without_long_wait():
    deadline = _resolve_runtime_deadline(wait_seconds=30, wait_until_finished=False, max_wait_seconds=999)

    assert deadline is not None


def test_terminal_audit_status_helper():
    assert _is_terminal_audit_status("done") is True
    assert _is_terminal_audit_status("failed") is True
    assert _is_terminal_audit_status("auditing") is False


def test_runtime_watch_line_uses_ui_runtime_summary():
    line = _build_runtime_watch_line(
        status={
            "status": "auditing",
            "progress": 18,
            "current_step": "空间一致性 Skill 执行复核",
            "ui_runtime": {
                "chief": {"assigned_task_count": 21},
                "worker_sessions": [{"session_key": "assignment:hyp-1"}],
            },
        },
        runtime_tasks=[],
        runtime_results=[{"id": "r1"}],
    )

    assert "status=auditing" in line
    assert "assignments=21" in line
    assert "visible_workers=1" in line
    assert "results=1" in line
