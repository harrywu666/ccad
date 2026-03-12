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


RUN_MODES = ("legacy", "chief_review", "shadow_compare", "assignment_final_review")


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
    normalized = str(run_mode or "legacy").strip().lower() or "legacy"
    if normalized == "shadow_compare":
        return ["legacy", "chief_review"]
    if normalized in {"legacy", "chief_review", "assignment_final_review"}:
        return [normalized]
    return ["legacy"]


def _finding_signature(item: Dict[str, Any]) -> str:
    return "|".join(
        [
            str(item.get("rule_id") or "").strip(),
            str(item.get("finding_type") or "").strip(),
            str(item.get("location") or "").strip(),
            str(item.get("sheet_no_a") or "").strip(),
            str(item.get("sheet_no_b") or "").strip(),
        ]
    )


def _extract_run_duration_seconds(runtime_audit: Dict[str, Any]) -> Optional[float]:
    status = runtime_audit.get("status") if isinstance(runtime_audit, dict) else {}
    if not isinstance(status, dict):
        return None
    started_at = _parse_datetime(status.get("started_at"))
    finished_at = _parse_datetime(status.get("finished_at"))
    if started_at is None or finished_at is None:
        return None
    return round((finished_at - started_at).total_seconds(), 3)


def _is_successful_runtime(runtime_audit: Dict[str, Any]) -> bool:
    status = runtime_audit.get("status") if isinstance(runtime_audit, dict) else {}
    if not isinstance(status, dict):
        return False
    status_value = str(status.get("status") or "").strip().lower()
    return status_value in {"done", "completed"}


def build_shadow_compare_summary(reports: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    legacy = reports.get("legacy") or {}
    chief_review = reports.get("chief_review") or {}
    legacy_results = list((legacy.get("artifacts") or {}).get("runtime_results") or [])
    chief_results = list((chief_review.get("artifacts") or {}).get("runtime_results") or [])
    legacy_signatures = {_finding_signature(item) for item in legacy_results}
    chief_signatures = {_finding_signature(item) for item in chief_results}

    overlap = legacy_signatures & chief_signatures
    legacy_only = legacy_signatures - chief_signatures
    chief_only = chief_signatures - legacy_signatures

    legacy_audit = ((legacy.get("checks") or {}).get("runtime_audit") or {})
    chief_audit = ((chief_review.get("checks") or {}).get("runtime_audit") or {})
    legacy_status = legacy_audit.get("status") if isinstance(legacy_audit, dict) else {}
    chief_status = chief_audit.get("status") if isinstance(chief_audit, dict) else {}
    legacy_pipeline_mode = str((legacy_status or {}).get("pipeline_mode") or "").strip() or None
    chief_pipeline_mode = str((chief_status or {}).get("pipeline_mode") or "").strip() or None
    legacy_duration_seconds = _extract_run_duration_seconds(legacy_audit)
    chief_duration_seconds = _extract_run_duration_seconds(chief_audit)
    overlap_ratio = round(len(overlap) / len(legacy_signatures | chief_signatures), 3) if (legacy_signatures or chief_signatures) else 1.0
    legacy_only_ratio = round(len(legacy_only) / len(legacy_signatures), 3) if legacy_signatures else 0.0
    chief_review_only_ratio = round(len(chief_only) / len(chief_signatures), 3) if chief_signatures else 0.0
    duration_delta_seconds = None
    if legacy_duration_seconds is not None and chief_duration_seconds is not None:
        duration_delta_seconds = round(chief_duration_seconds - legacy_duration_seconds, 3)

    gate_reasons: List[str] = []
    if not _is_successful_runtime(legacy_audit):
        gate_reasons.append("legacy_runtime_incomplete")
    if not _is_successful_runtime(chief_audit):
        gate_reasons.append("chief_review_runtime_incomplete")
    if legacy_audit.get("audit_version") and chief_audit.get("audit_version") and legacy_audit.get("audit_version") == chief_audit.get("audit_version"):
        gate_reasons.append("shadow_runs_not_isolated")
    if legacy_pipeline_mode and chief_pipeline_mode and legacy_pipeline_mode == chief_pipeline_mode:
        gate_reasons.append("pipeline_modes_not_diverged")
    if overlap_ratio < 0.8:
        gate_reasons.append("overlap_below_threshold")
    if legacy_only_ratio > 0.2:
        gate_reasons.append("legacy_miss_rate_too_high")
    if chief_review_only_ratio > 0.2:
        gate_reasons.append("chief_review_new_findings_too_high")
    if duration_delta_seconds is not None and duration_delta_seconds > 30.0:
        gate_reasons.append("chief_review_duration_regression")

    return {
        "legacy_audit_version": legacy_audit.get("audit_version"),
        "chief_review_audit_version": chief_audit.get("audit_version"),
        "legacy_result_count": len(legacy_results),
        "chief_review_result_count": len(chief_results),
        "legacy_pipeline_mode": legacy_pipeline_mode,
        "chief_review_pipeline_mode": chief_pipeline_mode,
        "overlap_count": len(overlap),
        "legacy_only_count": len(legacy_only),
        "chief_review_only_count": len(chief_only),
        "overlap_ratio": overlap_ratio,
        "legacy_only_ratio": legacy_only_ratio,
        "chief_review_only_ratio": chief_review_only_ratio,
        "legacy_duration_seconds": legacy_duration_seconds,
        "chief_review_duration_seconds": chief_duration_seconds,
        "duration_delta_seconds": duration_delta_seconds,
        "ready_for_cutover": not gate_reasons,
        "gate_reasons": gate_reasons,
    }


def _run_mode_env(run_mode: str) -> Dict[str, Optional[str]]:
    normalized = resolve_run_modes(run_mode)[0]
    shadow_label = None
    chief_enabled = None
    legacy_pipeline_allowed = None
    forced_pipeline_mode = None
    if normalized in {"chief_review", "assignment_final_review"}:
        shadow_label = "shadow_assignment_final_review" if normalized == "assignment_final_review" else "shadow_chief_review"
        chief_enabled = "1"
        legacy_pipeline_allowed = "0"
    elif normalized == "legacy":
        shadow_label = "shadow_legacy"
        chief_enabled = "0"
        legacy_pipeline_allowed = "1"
        forced_pipeline_mode = "legacy"
    return {
        "AUDIT_CHIEF_REVIEW_ENABLED": chief_enabled,
        "AUDIT_LEGACY_PIPELINE_ALLOWED": legacy_pipeline_allowed,
        "AUDIT_FORCE_PIPELINE_MODE": forced_pipeline_mode,
        "AUDIT_SHADOW_RUN_MODE": shadow_label,
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


def _count_grounded_final_issues(runtime_results: List[Dict[str, Any]]) -> int:
    grounded = 0
    for item in runtime_results:
        evidence = _safe_json_loads(item.get("evidence_json"))
        finding = evidence.get("finding") if isinstance(evidence.get("finding"), dict) else {}
        anchors = finding.get("anchors") if isinstance(finding.get("anchors"), list) else evidence.get("anchors")
        if not isinstance(anchors, list):
            continue
        for anchor in anchors:
            if not isinstance(anchor, dict):
                continue
            point = anchor.get("global_pct")
            region = anchor.get("highlight_region")
            if isinstance(point, dict) and point.get("x") is not None and point.get("y") is not None:
                grounded += 1
                break
            if (
                isinstance(region, dict)
                and isinstance(region.get("bbox_pct"), dict)
                and region["bbox_pct"].get("width") not in (None, 0)
                and region["bbox_pct"].get("height") not in (None, 0)
            ):
                grounded += 1
                break
    return grounded


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


def _summarize_runtime_failures(runtime_events: List[Dict[str, Any]]) -> Dict[str, Any]:
    failed_events = [
        event
        for event in runtime_events
        if str(event.get("event_kind") or "").strip() == "runner_session_failed"
    ]
    last_failure = failed_events[-1] if failed_events else {}
    message = str(last_failure.get("message") or "").strip() or None
    blocking_reason = None
    if message and ("KIMI_OFFICIAL_API_KEY" in message or "MOONSHOT_API_KEY" in message or "OPENROUTER_API_KEY" in message):
        blocking_reason = "missing_provider_env"
    return {
        "failed_runner_event_count": len(failed_events),
        "last_failure_message": message,
        "last_failure_event_kind": str(last_failure.get("event_kind") or "").strip() or None,
        "blocking_reason": blocking_reason,
    }


def build_assignment_final_review_summary(payload: Dict[str, Any]) -> Dict[str, Any]:
    status = payload.get("status") if isinstance(payload.get("status"), dict) else {}
    ui_runtime = status.get("ui_runtime") if isinstance(status.get("ui_runtime"), dict) else {}
    chief_runtime = ui_runtime.get("chief") if isinstance(ui_runtime.get("chief"), dict) else {}
    worker_sessions = ui_runtime.get("worker_sessions") if isinstance(ui_runtime.get("worker_sessions"), list) else []
    runtime_tasks = payload.get("runtime_tasks") if isinstance(payload.get("runtime_tasks"), list) else []
    runtime_results = payload.get("runtime_results") if isinstance(payload.get("runtime_results"), list) else []
    runtime_events = payload.get("runtime_events") if isinstance(payload.get("runtime_events"), list) else []
    runtime_report = payload.get("runtime_report") if isinstance(payload.get("runtime_report"), dict) else {}
    provider_preflight = payload.get("provider_preflight") if isinstance(payload.get("provider_preflight"), dict) else {}
    organizer_markdown_available = bool(payload.get("organizer_markdown_available"))
    assigned_task_count = chief_runtime.get("assigned_task_count")
    assigned_task_count = int(assigned_task_count) if isinstance(assigned_task_count, (int, float, str)) and str(assigned_task_count).strip().isdigit() else 0
    assignment_count = max(len(runtime_tasks), assigned_task_count)
    visible_worker_keys = {
        str(item.get("session_key") or "").strip()
        for item in worker_sessions
        if str(item.get("session_key") or "").strip()
    }
    for event in runtime_events:
        meta = event.get("meta") if isinstance(event.get("meta"), dict) else {}
        visible_key = str(meta.get("visible_session_key") or "").strip()
        if visible_key:
            visible_worker_keys.add(visible_key)
        assignment_id = str(meta.get("assignment_id") or "").strip()
        if assignment_id:
            visible_worker_keys.add(f"assignment:{assignment_id}")
    final_review_visible = isinstance(ui_runtime.get("final_review"), dict)
    organizer_visible = isinstance(ui_runtime.get("organizer"), dict)
    current_step = str(status.get("current_step") or "").strip()
    if not final_review_visible:
        final_review_visible = "终审" in current_step or any(
            "终审" in str(event.get("message") or "")
            for event in runtime_events
        )
    if not organizer_visible:
        organizer_visible = (
            "汇总" in current_step
            or "收束" in current_step
            or organizer_markdown_available
        )
    failure_summary = _summarize_runtime_failures(runtime_events)
    blocking_reason = failure_summary["blocking_reason"]
    if not blocking_reason and provider_preflight and provider_preflight.get("ok") is False:
        blocking_reason = "missing_provider_env"
    last_failure_message = failure_summary["last_failure_message"]
    if not last_failure_message and provider_preflight and provider_preflight.get("ok") is False:
        last_failure_message = str(provider_preflight.get("detail") or "").strip() or None

    return {
        "pipeline_mode": "assignment_final_review",
        "runtime_pipeline_mode": str(status.get("pipeline_mode") or "").strip() or None,
        "assignment_count": assignment_count,
        "visible_worker_card_count": len(visible_worker_keys),
        "worker_card_not_exceed_assignment_count": len(visible_worker_keys) <= assignment_count,
        "final_review_visible": final_review_visible,
        "organizer_visible": organizer_visible,
        "organizer_markdown_output": organizer_markdown_available,
        "grounded_final_issue_count": _count_grounded_final_issues(runtime_results),
        "marked_report_generated": str(runtime_report.get("mode") or "").strip().lower() == "marked",
        "anchors_json_path": runtime_report.get("anchors_json_path"),
        "provider_preflight_ok": provider_preflight.get("ok") if provider_preflight else None,
        "blocking_reason": blocking_reason,
        "failed_runner_event_count": failure_summary["failed_runner_event_count"],
        "last_failure_message": last_failure_message,
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
    parser.add_argument("--provider-mode", choices=["api", "openrouter"], help="Per-audit provider mode to request")
    parser.add_argument(
        "--run-mode",
        choices=list(RUN_MODES),
        default="legacy",
        help="Audit run mode: legacy, chief_review, shadow_compare, or assignment_final_review",
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
            provider_preflight = _provider_preflight(args.provider_mode)
            report["checks"]["provider_preflight"] = {
                "mode": "local",
                **provider_preflight,
            }
            if provider_preflight.get("ok") is False:
                if effective_run_mode == "assignment_final_review":
                    report["checks"]["assignment_final_review"] = build_assignment_final_review_summary(
                        {
                            "status": {},
                            "runtime_tasks": [],
                            "runtime_results": [],
                            "runtime_events": [],
                            "runtime_report": {},
                            "organizer_markdown_available": False,
                            "provider_preflight": provider_preflight,
                        }
                    )
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

        prompts_resp = client.get("/api/settings/ai-prompts")
        if prompts_resp.status_code != 200:
            report["checks"]["prompt_settings"] = {
                "ok": False,
                "status_code": prompts_resp.status_code,
                "detail": prompts_resp.text,
            }
            save_report(output_path, report)
            print(f"[ERROR] failed to load prompts, report saved: {output_path}")
            return 3, report, output_path

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
                    if effective_run_mode == "assignment_final_review":
                        report["checks"]["assignment_final_review"] = build_assignment_final_review_summary(
                            {
                                "status": runtime_status,
                                "runtime_tasks": runtime_tasks,
                                "runtime_results": runtime_results,
                                "runtime_events": runtime_events,
                                "runtime_report": runtime_report,
                                "organizer_markdown_available": organizer_markdown_available,
                                "provider_preflight": report["checks"].get("provider_preflight"),
                            }
                        )

        save_report(output_path, report)
        print(f"[INFO] report saved: {output_path}")
        print("[INFO] prompt settings check:", json.dumps(report["checks"]["prompt_settings"], ensure_ascii=False, indent=2))
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
    if args.run_mode == "shadow_compare":
        reports: Dict[str, Dict[str, Any]] = {}
        combined_exit_code = 0
        artifact_paths: Dict[str, str] = {}
        for mode in effective_modes:
            exit_code, report, output_path = _run_single_check(args, effective_run_mode=mode)
            reports[mode] = report
            artifact_paths[mode] = str(output_path)
            combined_exit_code = combined_exit_code or exit_code

        backend_dir = Path(__file__).resolve().parents[1]
        output_dir = backend_dir.parent / ".artifacts" / "manual-checks"
        combined_output_path = output_dir / _build_output_name(args, "shadow_compare")
        combined_report = {
            "project_id": args.project_id,
            "run_mode": "shadow_compare",
            "checked_at": datetime.now().isoformat(),
            "inputs": {
                "provider_mode": args.provider_mode,
                "base_url": args.base_url,
                "start_audit": args.start_audit,
            },
            "checks": {
                "shadow_compare": build_shadow_compare_summary(reports),
            },
            "artifacts": {
                "runs": reports,
                "run_reports": artifact_paths,
            },
        }
        save_report(combined_output_path, combined_report)
        print(f"[INFO] shadow compare report saved: {combined_output_path}")
        print("[INFO] shadow compare summary:", json.dumps(combined_report["checks"]["shadow_compare"], ensure_ascii=False, indent=2))
        return combined_exit_code

    exit_code, _report, _output_path = _run_single_check(args, effective_run_mode=effective_modes[0])
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
