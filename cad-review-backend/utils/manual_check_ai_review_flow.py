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


RUN_MODES = ("review_kernel",)


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


def summarize_runner_metrics(
    events: List[Dict[str, Any]],
    *,
    requested_provider_mode: Optional[str] = None,
    runtime_status: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    provider_mode = str(requested_provider_mode or "").strip().lower() or None
    sdk_session_reuse_count = 0
    sdk_repair_attempts = 0
    sdk_repair_successes = 0
    sdk_stream_event_count = 0
    sdk_needs_review_count = 0
    stalled_turn_retries = 0
    invalid_input_skipped = 0
    runner_broadcast_count = 0
    needs_review_count = 0
    observer_decision_count = 0
    observer_intervention_suggested_count = 0
    observer_auto_action_count = 0
    provider_names: set[str] = set()

    for event in events:
        meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
        provider_name = str(meta.get("provider_name") or "").strip().lower()
        provider_mode_hint = str(meta.get("provider_mode") or "").strip().lower()
        effective_provider = provider_mode_hint or provider_name
        if effective_provider:
            provider_names.add(effective_provider)
        event_kind = str(event.get("event_kind") or "").strip()
        if event_kind == "runner_turn_retrying":
            stalled_turn_retries += 1
        elif event_kind == "runner_input_skipped":
            invalid_input_skipped += 1
        elif event_kind == "runner_broadcast":
            runner_broadcast_count += 1
        elif event_kind in {"runner_turn_deferred", "runner_turn_needs_review"}:
            needs_review_count += 1
            if effective_provider == "sdk":
                sdk_needs_review_count += 1
        elif event_kind == "runner_observer_decision":
            observer_decision_count += 1
            if meta.get("should_intervene") is True:
                observer_intervention_suggested_count += 1
            if str(meta.get("suggested_action") or "").strip() in {"observe_only", "broadcast_update"}:
                observer_auto_action_count += 1
        if effective_provider == "sdk":
            if event_kind == "runner_session_reused":
                sdk_session_reuse_count += 1
            elif event_kind == "output_repair_started":
                sdk_repair_attempts += 1
            elif event_kind == "output_repair_succeeded":
                sdk_repair_successes += 1
            elif event_kind == "provider_stream_delta":
                sdk_stream_event_count += 1
    if not provider_mode:
        status_provider_mode = str((runtime_status or {}).get("provider_mode") or "").strip().lower()
        if status_provider_mode:
            provider_mode = status_provider_mode
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
        "sdk_stream_event_count": sdk_stream_event_count,
        "sdk_needs_review_count": sdk_needs_review_count,
        "stalled_turn_retries": stalled_turn_retries,
        "invalid_input_skipped": invalid_input_skipped,
        "runner_broadcast_count": runner_broadcast_count,
        "needs_review_count": needs_review_count,
        "observer_decision_count": observer_decision_count,
        "observer_intervention_suggested_count": observer_intervention_suggested_count,
        "observer_auto_action_count": observer_auto_action_count,
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


def resolve_run_modes(run_mode: Optional[str]) -> List[str]:
    return ["review_kernel"]


def _run_mode_env(run_mode: str) -> Dict[str, Optional[str]]:
    del run_mode
    return {
        "AUDIT_CHIEF_REVIEW_ENABLED": "1",
        "AUDIT_LEGACY_PIPELINE_ALLOWED": "0",
        "AUDIT_FORCE_PIPELINE_MODE": "review_kernel_v1",
        "AUDIT_SHADOW_RUN_MODE": "review_kernel",
    }


def _safe_json_loads(payload: Any) -> Dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    text = str(payload or "").strip()
    if not text:
        return {}
    try:
        value = json.loads(text)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _load_local_env_file(backend_dir: Path) -> None:
    env_path = backend_dir / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, value = stripped.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _local_provider_env_overrides(provider_mode: Optional[str]) -> Dict[str, Optional[str]]:
    normalized = str(provider_mode or "").strip().lower()
    if normalized == "openrouter":
        return {"KIMI_PROVIDER": "openrouter"}
    if normalized == "api":
        return {"KIMI_PROVIDER": "official"}
    return {}


def _provider_preflight(provider_mode: Optional[str]) -> Dict[str, Any]:
    normalized = str(provider_mode or "").strip().lower()
    if not normalized:
        return {
            "ok": True,
            "skipped": True,
            "detail": "未显式指定 provider_mode，跳过本地 provider 环境预检。",
        }

    required_env: List[str]
    if normalized == "openrouter":
        required_env = ["OPENROUTER_API_KEY"]
    else:
        required_env = ["KIMI_OFFICIAL_API_KEY", "MOONSHOT_API_KEY"]
    present_env = [
        name
        for name in required_env
        if str(os.getenv(name) or "").strip()
    ]
    missing_env = [name for name in required_env if name not in present_env]
    ok = bool(present_env)
    if ok:
        detail = f"provider 预检通过，已检测到 {present_env[0]}。"
    else:
        detail = f"缺少 provider 环境变量：{' / '.join(required_env)}。"
    return {
        "ok": ok,
        "skipped": False,
        "provider_mode": normalized,
        "required_env": required_env,
        "present_env": present_env,
        "missing_env": missing_env,
        "detail": detail,
    }


def _build_output_name(args: argparse.Namespace, effective_run_mode: str) -> str:
    output_name = f"{args.project_id}-{effective_run_mode}-runner-supervisor-check.json"
    if args.provider_mode:
        output_name = f"{args.project_id}-{effective_run_mode}-{args.provider_mode}-runner-supervisor-check.json"
    if args.base_url:
        safe_host = args.base_url.replace("://", "_").replace("/", "_").replace(":", "_")
        output_name = f"{args.project_id}-{effective_run_mode}-{safe_host}-runner-supervisor-check.json"
        if args.provider_mode:
            output_name = f"{args.project_id}-{effective_run_mode}-{args.provider_mode}-{safe_host}-runner-supervisor-check.json"
    return output_name


def _is_terminal_audit_status(value: Any) -> bool:
    normalized = str(value or "").strip().lower()
    return normalized in {"done", "completed", "failed"}


def _resolve_runtime_deadline(
    *,
    wait_seconds: float,
    wait_until_finished: bool,
    max_wait_seconds: Optional[float],
) -> Optional[float]:
    if wait_until_finished:
        if max_wait_seconds is None or max_wait_seconds <= 0:
            return None
        return time.time() + max_wait_seconds
    return time.time() + max(wait_seconds, 0.0)


def _deadline_remaining_seconds(deadline_ts: Optional[float]) -> Optional[float]:
    if deadline_ts is None:
        return None
    return max(0.0, deadline_ts - time.time())


def _build_runtime_watch_line(
    *,
    status: Dict[str, Any],
    runtime_tasks: List[Dict[str, Any]],
    runtime_results: List[Dict[str, Any]],
) -> str:
    ui_runtime = status.get("ui_runtime") if isinstance(status.get("ui_runtime"), dict) else {}
    chief_runtime = ui_runtime.get("chief") if isinstance(ui_runtime.get("chief"), dict) else {}
    worker_sessions = ui_runtime.get("worker_sessions") if isinstance(ui_runtime.get("worker_sessions"), list) else []
    return (
        f"status={str(status.get('status') or '').strip() or '-'} "
        f"progress={status.get('progress')} "
        f"step={str(status.get('current_step') or '').strip() or '-'} "
        f"assignments={chief_runtime.get('assigned_task_count') or len(runtime_tasks)} "
        f"visible_workers={len(worker_sessions)} "
        f"results={len(runtime_results)}"
    )


def poll_runtime_snapshot(
    client,
    *,
    project_id: str,
    version: int,
    interval_seconds: float,
    deadline_ts: Optional[float],
    wait_until_finished: bool,
) -> Dict[str, Any]:
    runtime_tasks: List[Dict[str, Any]] = []
    runtime_results: List[Dict[str, Any]] = []
    runtime_status: Dict[str, Any] = {}
    runtime_history: List[Dict[str, Any]] = []
    runtime_events: List[Dict[str, Any]] = []
    last_watch_line = None
    poll_count = 0

    while True:
        tasks_resp = client.get(f"/api/projects/{project_id}/audit/tasks", params={"version": version})
        if tasks_resp.status_code == 200:
            payload = tasks_resp.json()
            if isinstance(payload, list):
                runtime_tasks = payload

        results_resp = client.get(
            f"/api/projects/{project_id}/audit/results",
            params={"version": version, "view": "flat"},
        )
        if results_resp.status_code == 200:
            payload = results_resp.json()
            if isinstance(payload, list):
                runtime_results = payload

        status_resp = client.get(f"/api/projects/{project_id}/audit/status")
        if status_resp.status_code == 200:
            payload = status_resp.json()
            if isinstance(payload, dict):
                runtime_status = payload

        watch_line = _build_runtime_watch_line(
            status=runtime_status,
            runtime_tasks=runtime_tasks,
            runtime_results=runtime_results,
        )
        if watch_line != last_watch_line or poll_count % 20 == 0:
            remaining_seconds = _deadline_remaining_seconds(deadline_ts)
            if remaining_seconds is None:
                print(f"[WATCH] {watch_line} remaining=unbounded")
            else:
                print(f"[WATCH] {watch_line} remaining={round(remaining_seconds, 1)}s")
            last_watch_line = watch_line

        status_value = str(runtime_status.get("status") or "").strip().lower()
        if _is_terminal_audit_status(status_value):
            break
        if deadline_ts is not None and time.time() >= deadline_ts:
            break
        poll_count += 1
        time.sleep(interval_seconds)

    runtime_history_resp = client.get(f"/api/projects/{project_id}/audit/history")
    if runtime_history_resp.status_code == 200:
        payload = runtime_history_resp.json()
        if isinstance(payload, list):
            runtime_history = payload

    runtime_events_resp = client.get(
        f"/api/projects/{project_id}/audit/events",
        params={"version": version, "limit": 200},
    )
    if runtime_events_resp.status_code == 200:
        payload = runtime_events_resp.json()
        if isinstance(payload, dict):
            items = payload.get("items")
            if isinstance(items, list):
                runtime_events = items

    return {
        "runtime_tasks": runtime_tasks,
        "runtime_results": runtime_results,
        "runtime_status": runtime_status,
        "runtime_history": runtime_history,
        "runtime_events": runtime_events,
    }


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
    parser.add_argument("--wait-until-finished", action="store_true", help="Keep polling until audit reaches done/completed/failed")
    parser.add_argument("--max-wait-seconds", type=float, help="Optional hard cap when --wait-until-finished is enabled")
    parser.add_argument("--poll-interval", type=float, default=1.5, help="Polling interval in seconds")
    parser.add_argument("--base-url", help="Real backend base URL, for example http://127.0.0.1:7002")
    parser.add_argument("--request-timeout", type=float, default=12.0, help="Per-request timeout in seconds for HTTP mode")
    parser.add_argument("--db-path", help="Optional sqlite database path for edge inspection in HTTP mode")
    parser.add_argument("--enable-orchestrator-v2", action="store_true", help="Enable AUDIT_ORCHESTRATOR_V2_ENABLED in local mode")
    parser.add_argument("--enable-evidence-planner", action="store_true", help="Mark evidence planner enabled for this run")
    parser.add_argument("--enable-feedback-runtime", action="store_true", help="Mark feedback runtime injection enabled for this run")
    parser.add_argument("--provider-mode", choices=["api", "openrouter"], help="Per-audit provider mode to request")
    parser.add_argument(
        "--run-mode",
        choices=list(RUN_MODES),
        default="review_kernel",
        help="Audit run mode: review_kernel",
    )
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


def _run_single_check(
    args: argparse.Namespace,
    *,
    effective_run_mode: str,
) -> tuple[int, Dict[str, Any], Path]:
    backend_dir = Path(__file__).resolve().parents[1]
    output_dir = backend_dir.parent / ".artifacts" / "manual-checks"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / _build_output_name(args, effective_run_mode)

    report: Dict[str, Any] = {
        "project_id": args.project_id,
        "run_mode": effective_run_mode,
        "pipeline_mode": effective_run_mode,
        "checked_at": datetime.now().isoformat(),
        "inputs": {
            "start_audit": args.start_audit,
            "allow_incomplete": args.allow_incomplete,
            "wait_seconds": args.wait_seconds,
            "poll_interval": args.poll_interval,
            "base_url": args.base_url,
            "request_timeout": args.request_timeout,
            "provider_mode": args.provider_mode,
            "run_mode": effective_run_mode,
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
    local_db_module = None
    try:
        if args.base_url:
            client = HTTPAPIClient(args.base_url, args.request_timeout)
            db_path = detect_db_path(backend_dir, args.db_path)
            report["checks"]["runtime_switches"] = {
                "ok": True,
                "mode": "http",
                "applied": False,
                "provider_mode": args.provider_mode,
                "run_mode": effective_run_mode,
                "detail": "HTTP 模式不会远程改服务环境变量，仅记录本次验收期望开关。",
            }
        else:
            run_mode_env = _run_mode_env(effective_run_mode)
            provider_env = _local_provider_env_overrides(args.provider_mode)
            sys.path.insert(0, str(backend_dir))
            env_context = temporary_env(
                {
                    "AUDIT_ORCHESTRATOR_V2_ENABLED": "1" if args.enable_orchestrator_v2 else None,
                    "AUDIT_EVIDENCE_PLANNER_ENABLED": "1" if args.enable_evidence_planner else None,
                    "AUDIT_FEEDBACK_RUNTIME_ENABLED": "1" if args.enable_feedback_runtime else None,
                    **run_mode_env,
                    **provider_env,
                }
            )
            env_context.__enter__()
            _load_local_env_file(backend_dir)
            provider_preflight = _provider_preflight(args.provider_mode)
            report["checks"]["provider_preflight"] = {
                "mode": "local",
                **provider_preflight,
            }
            if provider_preflight.get("ok") is False:
                save_report(output_path, report)
                print(f"[ERROR] provider preflight failed, report saved: {output_path}")
                return 4, report, output_path
            import database  # noqa: WPS433
            database.init_db()
            from main import app  # noqa: WPS433

            local_db_module = database
            client = LocalAPIClient(TestClient(app))
            db_path = detect_db_path(backend_dir, args.db_path)
            report["checks"]["runtime_switches"] = {
                "ok": True,
                "mode": "local",
                "applied": True,
                "provider_mode": args.provider_mode,
                "run_mode": effective_run_mode,
                "values": {
                    "AUDIT_ORCHESTRATOR_V2_ENABLED": args.enable_orchestrator_v2,
                    "AUDIT_EVIDENCE_PLANNER_ENABLED": args.enable_evidence_planner,
                    "AUDIT_FEEDBACK_RUNTIME_ENABLED": args.enable_feedback_runtime,
                    "AUDIT_CHIEF_REVIEW_ENABLED": run_mode_env["AUDIT_CHIEF_REVIEW_ENABLED"] == "1",
                    "AUDIT_LEGACY_PIPELINE_ALLOWED": run_mode_env["AUDIT_LEGACY_PIPELINE_ALLOWED"],
                    "AUDIT_FORCE_PIPELINE_MODE": run_mode_env["AUDIT_FORCE_PIPELINE_MODE"],
                    "AUDIT_SHADOW_RUN_MODE": run_mode_env["AUDIT_SHADOW_RUN_MODE"],
                    "KIMI_PROVIDER": provider_env.get("KIMI_PROVIDER"),
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
            return 2, report, output_path
        report["checks"]["project_lookup"] = {"ok": True}

        assets_resp = client.get("/api/settings/agent-assets/review_kernel")
        if assets_resp.status_code != 200:
            report["checks"]["kernel_assets"] = {
                "ok": False,
                "status_code": assets_resp.status_code,
                "detail": assets_resp.text,
            }
            save_report(output_path, report)
            print(f"[ERROR] failed to load review kernel assets, report saved: {output_path}")
            return 3, report, output_path

        asset_items = assets_resp.json().get("items", [])
        asset_keys = {str(item.get("key") or "").strip() for item in asset_items if isinstance(item, dict)}
        required_keys = {
            "soul_core",
            "page_classifier_agent",
            "semantic_augmentor_agent",
            "review_reporter_agent",
            "review_qa_agent",
        }
        report["checks"]["kernel_assets"] = {
            "ok": required_keys.issubset(asset_keys),
            "required_keys": sorted(required_keys),
            "found_keys": sorted(asset_keys),
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
            return 4, report, output_path

        if plan_resp.status_code != 200:
            report["checks"]["plan_preview"] = {
                "ok": False,
                "status_code": plan_resp.status_code,
                "detail": plan_resp.text,
            }
            save_report(output_path, report)
            print(f"[ERROR] task planning failed, report saved: {output_path}")
            return 4, report, output_path

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
                    json_body={
                        "allow_incomplete": args.allow_incomplete,
                        "provider_mode": args.provider_mode,
                    },
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
                    deadline_ts = _resolve_runtime_deadline(
                        wait_seconds=args.wait_seconds,
                        wait_until_finished=args.wait_until_finished,
                        max_wait_seconds=args.max_wait_seconds,
                    )
                    runtime_snapshot = poll_runtime_snapshot(
                        client,
                        project_id=args.project_id,
                        version=runtime_version,
                        interval_seconds=args.poll_interval,
                        deadline_ts=deadline_ts,
                        wait_until_finished=args.wait_until_finished,
                    )
                    runtime_tasks = runtime_snapshot["runtime_tasks"]
                    runtime_results = runtime_snapshot["runtime_results"]
                    runtime_status = runtime_snapshot["runtime_status"]
                    runtime_history = runtime_snapshot["runtime_history"]
                    runtime_events = runtime_snapshot["runtime_events"]
                    runtime_summary = summarize_tasks(runtime_tasks)
                    progressive_metrics = summarize_progressive_metrics(
                        tasks=runtime_tasks,
                        results=runtime_results,
                        events=runtime_events,
                    )
                    runner_metrics = summarize_runner_metrics(
                        runtime_events,
                        requested_provider_mode=args.provider_mode,
                        runtime_status=runtime_status,
                    )
                    status_value = str(runtime_status.get("status") or "").strip().lower()
                    completed_within_window = status_value in {"done", "completed", "failed"}
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
                        "window_seconds": args.max_wait_seconds if args.wait_until_finished else args.wait_seconds,
                        "wait_until_finished": args.wait_until_finished,
                        "max_wait_seconds": args.max_wait_seconds,
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
                    organizer_markdown_available = any(
                        bool(
                            (
                                _safe_json_loads(item.get("evidence_json"))
                                .get("finding", {})
                                .get("organizer_markdown_block")
                            )
                        )
                        for item in runtime_results
                    )
                    report["artifacts"]["organizer_markdown_available"] = organizer_markdown_available
                    runtime_report: Dict[str, Any] = {}
                    if local_db_module is not None and completed_within_window:
                        try:
                            from models import AuditResult, Project  # noqa: WPS433
                            from services.report_service import generate_pdf  # noqa: WPS433

                            db = local_db_module.SessionLocal()
                            try:
                                project = db.query(Project).filter(Project.id == args.project_id).first()
                                runtime_db_results = (
                                    db.query(AuditResult)
                                    .filter(
                                        AuditResult.project_id == args.project_id,
                                        AuditResult.audit_version == runtime_version,
                                    )
                                    .all()
                                )
                                if project is not None and runtime_db_results:
                                    runtime_report = generate_pdf(project, runtime_db_results, runtime_version, db=db, mode="marked")
                            finally:
                                db.close()
                        except Exception as exc:  # noqa: BLE001
                            runtime_report = {"mode": "error", "error": str(exc)}
                    if runtime_report:
                        report["artifacts"]["runtime_report"] = runtime_report

        save_report(output_path, report)
        print(f"[INFO] report saved: {output_path}")
        print("[INFO] kernel assets check:", json.dumps(report["checks"]["kernel_assets"], ensure_ascii=False, indent=2))
        print("[INFO] plan preview check:", json.dumps(report["checks"]["plan_preview"], ensure_ascii=False, indent=2))
        if "runtime_audit" in report["checks"]:
            print("[INFO] runtime audit check:", json.dumps(report["checks"]["runtime_audit"], ensure_ascii=False, indent=2))
        return 0, report, output_path
    finally:
        if client is not None:
            client.close()
        if env_context is not None:
            env_context.__exit__(None, None, None)


def main() -> int:
    args = parse_args()
    effective_modes = resolve_run_modes(args.run_mode)
    exit_code, _report, _output_path = _run_single_check(args, effective_run_mode=effective_modes[0])
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
