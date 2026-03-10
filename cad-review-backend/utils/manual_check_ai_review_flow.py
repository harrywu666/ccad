#!/usr/bin/env python3
"""
Manual AI review flow checker.

Runs a structured verification flow against an existing project and saves a JSON
report under .artifacts/manual-checks/.

Usage:
  ./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <id>
  ./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <id> --start-audit
  ./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <id> --base-url http://127.0.0.1:7002
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from collections import Counter
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from fastapi.testclient import TestClient


class ClientResponse:
    def __init__(self, status_code: int, text: str, payload: Any = None):
        self.status_code = status_code
        self.text = text
        self._payload = payload

    def json(self) -> Any:
        if self._payload is not None:
            return self._payload
        return json.loads(self.text)


class LocalAPIClient:
    def __init__(self, client: TestClient):
        self._client = client

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> ClientResponse:
        response = self._client.get(path, params=params)
        return ClientResponse(response.status_code, response.text, response.json() if response.content else None)

    def post(
        self,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> ClientResponse:
        response = self._client.post(path, json=json_body, params=params)
        return ClientResponse(response.status_code, response.text, response.json() if response.content else None)

    def close(self) -> None:
        self._client.close()


class HTTPAPIClient:
    def __init__(self, base_url: str, timeout_seconds: float):
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_seconds,
            follow_redirects=True,
            trust_env=False,
        )

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> ClientResponse:
        response = self._client.get(path, params=params)
        return ClientResponse(response.status_code, response.text)

    def post(
        self,
        path: str,
        *,
        json_body: Optional[Dict[str, Any]] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> ClientResponse:
        response = self._client.post(path, json=json_body, params=params)
        return ClientResponse(response.status_code, response.text)

    def close(self) -> None:
        self._client.close()


def summarize_tasks(tasks: List[Dict[str, Any]]) -> Dict[str, int]:
    counts = Counter(str(task.get("task_type") or "") for task in tasks)
    return {
        "total": len(tasks),
        "index_tasks": counts.get("index", 0),
        "dimension_tasks": counts.get("dimension", 0),
        "material_tasks": counts.get("material", 0),
    }


def compute_structured_finding_coverage(results: List[Dict[str, Any]]) -> float:
    if not results:
        return 1.0

    required_fields = (
        "rule_id",
        "finding_type",
        "finding_status",
        "source_agent",
        "evidence_pack_id",
        "review_round",
        "confidence",
    )
    valid = 0
    for result in results:
        if all(result.get(field) not in (None, "", []) for field in required_fields):
            valid += 1
    return round(valid / len(results), 3)


def summarize_progressive_metrics(
    *,
    tasks: List[Dict[str, Any]],
    results: List[Dict[str, Any]],
    events: List[Dict[str, Any]],
) -> Dict[str, Any]:
    total_tasks = len(tasks)
    round_2_count = 0
    needs_review_count = 0

    for result in results:
        review_round = int(result.get("review_round") or 0)
        if review_round >= 2:
            round_2_count += 1
        if str(result.get("finding_status") or "").strip().lower() == "needs_review":
            needs_review_count += 1

    budget_usage: Dict[str, Any] = {}
    for event in events:
        meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
        snapshot = meta.get("budget_usage") if isinstance(meta, dict) else None
        if isinstance(snapshot, dict):
            budget_usage = snapshot

    return {
        "total_tasks": total_tasks,
        "round_2_count": round_2_count,
        "round_2_ratio": round(round_2_count / total_tasks, 3) if total_tasks else 0.0,
        "needs_review_count": needs_review_count,
        "budget_usage": budget_usage,
        "structured_finding_coverage": compute_structured_finding_coverage(results),
    }


def summarize_runner_metrics(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    provider_mode = str(os.getenv("AUDIT_RUNNER_PROVIDER", "")).strip().lower() or None
    sdk_session_reuse_count = 0
    sdk_repair_attempts = 0
    sdk_repair_successes = 0
    sdk_needs_review_count = 0
    sdk_stream_event_count = 0
    stalled_turn_retries = 0
    invalid_input_skipped = 0
    runner_broadcast_count = 0
    needs_review_count = 0
    provider_names: set[str] = set()

    for event in events:
        meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
        provider_name = str(meta.get("provider_name") or "").strip().lower()
        if provider_name:
            provider_names.add(provider_name)
        event_kind = str(event.get("event_kind") or "").strip()
        if event_kind == "runner_turn_retrying":
            stalled_turn_retries += 1
        elif event_kind == "runner_input_skipped":
            invalid_input_skipped += 1
        elif event_kind == "runner_broadcast":
            runner_broadcast_count += 1
        elif event_kind == "runner_turn_needs_review":
            needs_review_count += 1
        if provider_name != "sdk":
            continue
        if event_kind == "runner_session_reused":
            sdk_session_reuse_count += 1
        elif event_kind == "output_repair_started":
            sdk_repair_attempts += 1
        elif event_kind == "output_repair_succeeded":
            sdk_repair_successes += 1
        elif event_kind == "runner_turn_needs_review":
            sdk_needs_review_count += 1
        elif event_kind == "provider_stream_delta":
            sdk_stream_event_count += 1

    if not provider_mode and len(provider_names) == 1:
        provider_mode = next(iter(provider_names))

    last_progress_gap_seconds = None
    last_progress_at = None
    for event in reversed(events):
        event_kind = str(event.get("event_kind") or "").strip()
        if event_kind in {"heartbeat", "provider_stream_delta", "model_stream_delta"}:
            continue
        created_at = _parse_datetime(event.get("created_at"))
        if created_at is None:
            continue
        last_progress_at = created_at
        last_progress_gap_seconds = round(
            max(0.0, (datetime.now() - created_at).total_seconds()),
            3,
        )
        break

    return {
        "provider_mode": provider_mode,
        "provider_names_seen": sorted(provider_names),
        "sdk_session_reuse_count": sdk_session_reuse_count,
        "sdk_repair_attempts": sdk_repair_attempts,
        "sdk_repair_successes": sdk_repair_successes,
        "sdk_needs_review_count": sdk_needs_review_count,
        "sdk_stream_event_count": sdk_stream_event_count,
        "stalled_turn_retries": stalled_turn_retries,
        "invalid_input_skipped": invalid_input_skipped,
        "runner_broadcast_count": runner_broadcast_count,
        "needs_review_count": needs_review_count,
        "last_progress_at": last_progress_at.isoformat() if last_progress_at else None,
        "last_progress_gap_seconds": last_progress_gap_seconds,
    }


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def wait_for_tasks(
    client,
    project_id: str,
    version: int,
    deadline_ts: float,
    interval_seconds: float,
) -> List[Dict[str, Any]]:
    latest: List[Dict[str, Any]] = []
    while time.time() < deadline_ts:
        resp = client.get(f"/api/projects/{project_id}/audit/tasks", params={"version": version})
        if resp.status_code == 200:
            latest = resp.json()
            if latest:
                return latest
        time.sleep(interval_seconds)
    return latest


def wait_for_results(
    client,
    project_id: str,
    version: int,
    deadline_ts: float,
    interval_seconds: float,
) -> List[Dict[str, Any]]:
    latest: List[Dict[str, Any]] = []
    while time.time() < deadline_ts:
        resp = client.get(
            f"/api/projects/{project_id}/audit/results",
            params={"version": version, "view": "flat"},
        )
        if resp.status_code == 200:
            latest = resp.json()
            if latest:
                return latest
        time.sleep(interval_seconds)
    return latest


def save_report(output_path: Path, report: Dict[str, Any]) -> None:
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def read_ai_edges(db_path: Optional[str], project_id: str) -> Dict[str, Any]:
    if not db_path:
        return {"available": False, "items": [], "count": None}

    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    try:
        rows = connection.execute(
            """
            select source_sheet_no, target_sheet_no, confidence
            from sheet_edges
            where project_id = ? and edge_type = 'ai_visual'
            order by source_sheet_no asc, target_sheet_no asc
            """,
            (project_id,),
        ).fetchall()
    finally:
        connection.close()

    items = [
        {
            "source_sheet_no": row["source_sheet_no"],
            "target_sheet_no": row["target_sheet_no"],
            "confidence": row["confidence"],
        }
        for row in rows
    ]
    return {"available": True, "items": items, "count": len(items)}


def detect_db_path(backend_dir: Path, explicit_db_path: Optional[str]) -> Optional[str]:
    if explicit_db_path:
        return explicit_db_path

    candidate = Path.home() / "cad-review" / "db" / "database.sqlite"
    if candidate.exists():
        return str(candidate)

    sys.path.insert(0, str(backend_dir))
    try:
        import database  # noqa: WPS433
    except Exception:
        return None

    db_url = getattr(database, "DATABASE_URL", "")
    prefix = "sqlite:///"
    if db_url.startswith(prefix):
        return db_url[len(prefix):]
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-id", required=True, help="Existing project id")
    parser.add_argument("--start-audit", action="store_true", help="Also start the real audit run")
    parser.add_argument("--allow-incomplete", action="store_true", help="Allow incomplete three-line match")
    parser.add_argument("--wait-seconds", type=float, default=30.0, help="Polling timeout for runtime task creation")
    parser.add_argument("--poll-interval", type=float, default=1.5, help="Polling interval in seconds")
    parser.add_argument("--base-url", help="Real backend base URL, for example http://127.0.0.1:7002")
    parser.add_argument("--request-timeout", type=float, default=12.0, help="Per-request timeout in seconds for HTTP mode")
    parser.add_argument("--db-path", help="Optional sqlite database path for edge inspection in HTTP mode")
    parser.add_argument("--enable-orchestrator-v2", action="store_true", help="Enable AUDIT_ORCHESTRATOR_V2_ENABLED in local mode")
    parser.add_argument("--enable-evidence-planner", action="store_true", help="Mark evidence planner enabled for this run")
    parser.add_argument("--enable-feedback-runtime", action="store_true", help="Mark feedback runtime injection enabled for this run")
    return parser.parse_args()


@contextmanager
def temporary_env(overrides: Dict[str, Optional[str]]):
    import os

    old_values = {key: os.environ.get(key) for key in overrides}
    try:
        for key, value in overrides.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in old_values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def main() -> int:
    args = parse_args()

    backend_dir = Path(__file__).resolve().parents[1]
    output_dir = backend_dir.parent / ".artifacts" / "manual-checks"
    output_dir.mkdir(parents=True, exist_ok=True)

    output_name = f"{args.project_id}-runner-supervisor-check.json"
    if args.base_url:
        safe_host = args.base_url.replace("://", "_").replace("/", "_").replace(":", "_")
        output_name = f"{args.project_id}-{safe_host}-runner-supervisor-check.json"
    output_path = output_dir / output_name

    report: Dict[str, Any] = {
        "project_id": args.project_id,
        "checked_at": datetime.now().isoformat(),
        "inputs": {
            "start_audit": args.start_audit,
            "allow_incomplete": args.allow_incomplete,
            "wait_seconds": args.wait_seconds,
            "poll_interval": args.poll_interval,
            "base_url": args.base_url,
            "request_timeout": args.request_timeout,
            "enable_orchestrator_v2": args.enable_orchestrator_v2,
            "enable_evidence_planner": args.enable_evidence_planner,
            "enable_feedback_runtime": args.enable_feedback_runtime,
        },
        "checks": {},
        "artifacts": {},
    }

    client = None
    db_path = None
    env_context = None
    try:
        if args.base_url:
            client = HTTPAPIClient(args.base_url, args.request_timeout)
            db_path = detect_db_path(backend_dir, args.db_path)
            report["checks"]["runtime_switches"] = {
                "ok": True,
                "mode": "http",
                "applied": False,
                "provider_mode": os.getenv("AUDIT_RUNNER_PROVIDER"),
                "detail": "HTTP 模式不会远程改服务环境变量，仅记录本次验收期望开关。",
            }
        else:
            sys.path.insert(0, str(backend_dir))
            env_context = temporary_env(
                {
                    "AUDIT_ORCHESTRATOR_V2_ENABLED": "1" if args.enable_orchestrator_v2 else None,
                    "AUDIT_EVIDENCE_PLANNER_ENABLED": "1" if args.enable_evidence_planner else None,
                    "AUDIT_FEEDBACK_RUNTIME_ENABLED": "1" if args.enable_feedback_runtime else None,
                }
            )
            env_context.__enter__()
            import database  # noqa: WPS433
            database.init_db()
            from main import app  # noqa: WPS433

            client = LocalAPIClient(TestClient(app))
            db_path = detect_db_path(backend_dir, args.db_path)
            report["checks"]["runtime_switches"] = {
                "ok": True,
                "mode": "local",
                "applied": True,
                "provider_mode": os.getenv("AUDIT_RUNNER_PROVIDER"),
                "values": {
                    "AUDIT_ORCHESTRATOR_V2_ENABLED": args.enable_orchestrator_v2,
                    "AUDIT_EVIDENCE_PLANNER_ENABLED": args.enable_evidence_planner,
                    "AUDIT_FEEDBACK_RUNTIME_ENABLED": args.enable_feedback_runtime,
                },
            }

        project_resp = client.get(f"/api/projects/{args.project_id}")
        if project_resp.status_code != 200:
            report["checks"]["project_lookup"] = {
                "ok": False,
                "status_code": project_resp.status_code,
                "detail": project_resp.text,
            }
            save_report(output_path, report)
            print(f"[ERROR] project not found, report saved: {output_path}")
            return 2
        report["checks"]["project_lookup"] = {"ok": True}

        prompts_resp = client.get("/api/settings/ai-prompts")
        if prompts_resp.status_code != 200:
            report["checks"]["prompt_settings"] = {
                "ok": False,
                "status_code": prompts_resp.status_code,
                "detail": prompts_resp.text,
            }
            save_report(output_path, report)
            print(f"[ERROR] failed to load prompts, report saved: {output_path}")
            return 3

        stages = prompts_resp.json().get("stages", [])
        relationship_stage = next((s for s in stages if s.get("stage_key") == "sheet_relationship_discovery"), None)
        planner_stage = next((s for s in stages if s.get("stage_key") == "master_task_planner"), None)
        report["checks"]["prompt_settings"] = {
            "ok": bool(relationship_stage and planner_stage),
            "relationship_stage_present": bool(relationship_stage),
            "planner_stage_present": bool(planner_stage),
            "relationship_stage_updated_at": relationship_stage.get("updated_at") if relationship_stage else None,
            "planner_stage_updated_at": planner_stage.get("updated_at") if planner_stage else None,
            "relationship_prompt_preview": (relationship_stage.get("user_prompt", "")[:180] if relationship_stage else ""),
            "planner_prompt_preview": (planner_stage.get("user_prompt", "")[:180] if planner_stage else ""),
        }

        try:
            plan_resp = client.post(f"/api/projects/{args.project_id}/audit/tasks/plan", json_body={})
        except httpx.TimeoutException as exc:
            report["checks"]["plan_preview"] = {
                "ok": False,
                "error": "request_timeout",
                "detail": str(exc),
            }
            save_report(output_path, report)
            print(f"[ERROR] task planning timed out, report saved: {output_path}")
            return 4

        if plan_resp.status_code != 200:
            report["checks"]["plan_preview"] = {
                "ok": False,
                "status_code": plan_resp.status_code,
                "detail": plan_resp.text,
            }
            save_report(output_path, report)
            print(f"[ERROR] task planning failed, report saved: {output_path}")
            return 4

        plan_payload = plan_resp.json()
        planned_version = int(plan_payload["audit_version"])
        planned_tasks_resp = client.get(
            f"/api/projects/{args.project_id}/audit/tasks",
            params={"version": planned_version},
        )
        planned_tasks = planned_tasks_resp.json() if planned_tasks_resp.status_code == 200 else []
        ai_edge_snapshot = read_ai_edges(db_path, args.project_id)

        planned_summary_from_list = summarize_tasks(planned_tasks)
        report["checks"]["plan_preview"] = {
            "ok": True,
            "audit_version": planned_version,
            "relationship_summary": plan_payload.get("relationship_summary"),
            "task_summary_from_api": plan_payload.get("task_summary"),
            "task_summary_from_list": planned_summary_from_list,
            "summary_matches_list": {
                "index": plan_payload.get("task_summary", {}).get("index_tasks") == planned_summary_from_list["index_tasks"],
                "dimension": plan_payload.get("task_summary", {}).get("dimension_tasks") == planned_summary_from_list["dimension_tasks"],
                "material": plan_payload.get("task_summary", {}).get("material_tasks") == planned_summary_from_list["material_tasks"],
            },
            "ai_visual_edge_count": ai_edge_snapshot["count"],
            "ai_visual_edge_inspection_available": ai_edge_snapshot["available"],
        }
        report["artifacts"]["planned_tasks"] = planned_tasks
        report["artifacts"]["ai_visual_edges"] = ai_edge_snapshot["items"]

        if args.start_audit:
            try:
                start_resp = client.post(
                    f"/api/projects/{args.project_id}/audit/start",
                    json_body={"allow_incomplete": args.allow_incomplete},
                )
            except httpx.TimeoutException as exc:
                report["checks"]["runtime_audit"] = {
                    "ok": False,
                    "error": "request_timeout",
                    "detail": str(exc),
                }
            else:
                if start_resp.status_code != 200:
                    report["checks"]["runtime_audit"] = {
                        "ok": False,
                        "status_code": start_resp.status_code,
                        "detail": start_resp.text,
                    }
                else:
                    start_payload = start_resp.json()
                    runtime_version = int(start_payload["audit_version"])
                    deadline_ts = time.time() + args.wait_seconds
                    runtime_tasks = wait_for_tasks(
                        client,
                        args.project_id,
                        runtime_version,
                        deadline_ts,
                        args.poll_interval,
                    )
                    runtime_results = wait_for_results(
                        client,
                        args.project_id,
                        runtime_version,
                        deadline_ts,
                        args.poll_interval,
                    )
                    runtime_status_resp = client.get(f"/api/projects/{args.project_id}/audit/status")
                    runtime_history_resp = client.get(f"/api/projects/{args.project_id}/audit/history")
                    runtime_events_resp = client.get(
                        f"/api/projects/{args.project_id}/audit/events",
                        params={"version": runtime_version, "limit": 200},
                    )
                    runtime_status = runtime_status_resp.json() if runtime_status_resp.status_code == 200 else {}
                    runtime_history = runtime_history_resp.json() if runtime_history_resp.status_code == 200 else []
                    runtime_events_payload = runtime_events_resp.json() if runtime_events_resp.status_code == 200 else {}
                    runtime_events = runtime_events_payload.get("items", []) if isinstance(runtime_events_payload, dict) else []
                    runtime_summary = summarize_tasks(runtime_tasks)
                    progressive_metrics = summarize_progressive_metrics(
                        tasks=runtime_tasks,
                        results=runtime_results,
                        events=runtime_events,
                    )
                    runner_metrics = summarize_runner_metrics(runtime_events)
                    status_value = str(runtime_status.get("status") or "").strip().lower()
                    completed_within_window = status_value in {"completed", "failed"}
                    last_progress_gap_seconds = runner_metrics.get("last_progress_gap_seconds")
                    running_with_recent_progress = (
                        status_value == "running"
                        and isinstance(last_progress_gap_seconds, (int, float))
                        and float(last_progress_gap_seconds) <= max(args.poll_interval * 2, 15.0)
                    )
                    report["checks"]["runtime_audit"] = {
                        "ok": True,
                        "audit_version": runtime_version,
                        "status": runtime_status,
                        "completed_within_window": completed_within_window,
                        "window_seconds": args.wait_seconds,
                        "running_with_recent_progress": running_with_recent_progress,
                        "task_summary_from_list": runtime_summary,
                        "matches_plan_counts": (
                            runtime_summary["index_tasks"] == planned_summary_from_list["index_tasks"]
                            and runtime_summary["dimension_tasks"] == planned_summary_from_list["dimension_tasks"]
                            and runtime_summary["material_tasks"] == planned_summary_from_list["material_tasks"]
                        ),
                        "history_head": runtime_history[:3],
                        "progressive_metrics": progressive_metrics,
                        "runner_metrics": runner_metrics,
                    }
                    report["artifacts"]["runtime_tasks"] = runtime_tasks
                    report["artifacts"]["runtime_results"] = runtime_results
                    report["artifacts"]["runtime_events"] = runtime_events

        save_report(output_path, report)
        print(f"[INFO] report saved: {output_path}")
        print("[INFO] prompt settings check:", json.dumps(report["checks"]["prompt_settings"], ensure_ascii=False, indent=2))
        print("[INFO] plan preview check:", json.dumps(report["checks"]["plan_preview"], ensure_ascii=False, indent=2))
        if "runtime_audit" in report["checks"]:
            print("[INFO] runtime audit check:", json.dumps(report["checks"]["runtime_audit"], ensure_ascii=False, indent=2))
        return 0
    finally:
        if client is not None:
            client.close()
        if env_context is not None:
            env_context.__exit__(None, None, None)


if __name__ == "__main__":
    raise SystemExit(main())
