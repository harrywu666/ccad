"""新审图主链路：程序优先 + LLM 边界介入。"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

from database import SessionLocal
from models import AuditResult, JsonData, Project
from services.audit_runtime.cancel_registry import (
    AuditCancellationRequested,
    clear_cancel_request,
    is_cancel_requested,
)
from services.audit_runtime.state_transitions import (
    append_result_summary_event,
    append_result_upsert_events,
    append_run_event,
    set_project_status,
    update_run_progress,
)
from services.review_kernel.context_slicer import (
    build_context_slices,
    build_report_context_slice,
    find_slice_by_type,
)
from services.review_kernel.ir_compiler import compile_layout_ir, persist_layout_ir
from services.review_kernel.issue_policy import (
    apply_confidence_propagation,
    enforce_high_severity_constraint,
)
from services.review_kernel.llm_intervention import (
    apply_weak_assist,
    disambiguate_reference_bindings,
    polish_issue_writing,
)
from services.review_kernel.rule_engine import run_review_rules

logger = logging.getLogger(__name__)


def resolve_pipeline_mode() -> str:
    """全量重写后固定新链路，不再自动回退旧架构。"""
    raw = str(os.getenv("AUDIT_RUNTIME_PIPELINE_MODE") or "").strip().lower()
    if raw in {"", "review_kernel", "review_kernel_v1", "v3", "kernel"}:
        return "review_kernel_v1"
    return "review_kernel_v1"


def _event(
    project_id: str,
    audit_version: int,
    *,
    step_key: str,
    progress_hint: int,
    message: str,
    level: str = "info",
    meta: Optional[dict[str, Any]] = None,
) -> None:
    append_run_event(
        project_id,
        audit_version,
        level=level,
        step_key=step_key,
        agent_key="review_kernel",
        agent_name="审图内核",
        event_kind="phase_progress",
        progress_hint=progress_hint,
        message=message,
        meta={
            "pipeline_mode": "review_kernel_v1",
            "orchestration_model": "program_first_with_llm_boundary",
            "planner_source": "review_kernel",
            **(meta or {}),
        },
    )


def _load_json_payload(path: str) -> Optional[dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        logger.exception("读取 JSON 失败: %s", path)
        return None
    return payload if isinstance(payload, dict) else None


def _list_ready_json_rows(project_id: str, allow_incomplete: bool) -> list[JsonData]:
    db = SessionLocal()
    try:
        query = db.query(JsonData).filter(
            JsonData.project_id == project_id,
            JsonData.is_latest == 1,
        )
        if not allow_incomplete:
            query = query.filter(JsonData.status == "matched")
        rows = query.order_by(JsonData.created_at.asc()).all()
        return rows
    finally:
        db.close()


def _load_project_name(project_id: str) -> str:
    db = SessionLocal()
    try:
        row = db.query(Project).filter(Project.id == project_id).first()
        if not row:
            return ""
        return str(getattr(row, "name", "") or "").strip()
    finally:
        db.close()


def _check_cancel(project_id: str) -> None:
    if is_cancel_requested(project_id):
        raise AuditCancellationRequested("用户请求中断审核")


def _normalize_issue_type(category: Any) -> str:
    raw = str(category or "").strip().lower()
    if raw in {"index", "reference_broken", "cross_sheet_inconsistency", "detail_callout_binding"}:
        return "index"
    if raw in {"dimension", "dimension_conflict", "annotation_missing", "clearance_violation"}:
        return "dimension"
    if raw in {"material", "material_mismatch", "material_missing", "finish_conflict"}:
        return "material"
    return raw or "rule_issue"


def _normalize_finding_status(reviewed_status: Any) -> str:
    raw = str(reviewed_status or "").strip().lower()
    if raw in {"confirmed", "accepted"}:
        return "confirmed"
    if raw in {"suspected"}:
        return "suspected"
    return "needs_review"


def _format_location_for_ui(
    *,
    location: dict[str, Any],
    issue: dict[str, Any],
    evidence: dict[str, Any],
) -> str | None:
    sheet_no = str(location.get("sheet_no") or "").strip()
    logical_title = str(location.get("logical_sheet_title") or "").strip()
    if sheet_no and logical_title and logical_title != sheet_no:
        base = f"{sheet_no} / {logical_title}"
    else:
        base = sheet_no or logical_title

    category = str(issue.get("category") or "").strip().lower()
    if category == "reference_broken":
        target_sheet = str(evidence.get("target_sheet_no") or "").strip()
        if base and target_sheet:
            return f"{base} -> {target_sheet}"
        if target_sheet:
            return f"目标图号 {target_sheet}"

    if base:
        return base

    center = location.get("center_canonical")
    if isinstance(center, list) and len(center) >= 2:
        return "图纸坐标附近"
    return None


def _persist_issues(
    project_id: str,
    audit_version: int,
    issues: list[dict[str, Any]],
) -> list[str]:
    db = SessionLocal()
    try:
        db.query(AuditResult).filter(
            AuditResult.project_id == project_id,
            AuditResult.audit_version == audit_version,
        ).delete(synchronize_session=False)

        inserted: list[AuditResult] = []
        for issue in issues:
            evidence = issue.get("evidence") if isinstance(issue.get("evidence"), dict) else {}
            location = issue.get("location") if isinstance(issue.get("location"), dict) else {}
            finding_status = _normalize_finding_status(issue.get("reviewed_status"))
            normalized_type = _normalize_issue_type(issue.get("category"))
            location_text = _format_location_for_ui(location=location, issue=issue, evidence=evidence)
            row = AuditResult(
                project_id=project_id,
                audit_version=audit_version,
                type=normalized_type,
                severity=str(issue.get("severity") or "warning"),
                sheet_no_a=str(location.get("sheet_no") or "") or None,
                sheet_no_b=None,
                location=location_text,
                value_a=str(evidence.get("display_value") or evidence.get("measured_value") or "") or None,
                value_b=str(evidence.get("required_value") or evidence.get("target_sheet_no") or "") or None,
                rule_id=str(issue.get("rule_id") or "") or None,
                finding_type=str(issue.get("category") or "") or None,
                finding_status=finding_status,
                source_agent="review_kernel",
                triggered_by="review_kernel_rule_engine",
                confidence=float(issue.get("confidence") or 0.0),
                description=str(issue.get("description") or "") or None,
                evidence_json=json.dumps(issue, ensure_ascii=False),
            )
            inserted.append(row)
            db.add(row)
        db.commit()
        return [str(row.id) for row in inserted]
    finally:
        db.close()


def _finalize_run(
    project_id: str,
    audit_version: int,
    *,
    status: str,
    current_step: str,
    progress: int,
    total_issues: int,
    error: Optional[str],
    finished: bool,
) -> None:
    update_run_progress(
        project_id,
        audit_version,
        status=status,
        current_step=current_step,
        progress=progress,
        total_issues=total_issues,
        error=error,
        finished=finished,
    )
    if status == "done":
        set_project_status(project_id, "done")
    elif status in {"failed", "stopping"}:
        set_project_status(project_id, "ready")


def execute_pipeline(
    project_id: str,
    audit_version: int,
    *,
    allow_incomplete: bool = False,
    clear_running: Optional[Callable[[str], None]] = None,
    resume_existing: bool = False,
    worker_generation: Optional[int] = None,
    is_current_worker: Optional[Callable[[str, int], bool]] = None,
) -> None:
    """执行新内核审图流水线。"""
    del resume_existing

    issue_count = 0
    try:
        if is_current_worker and worker_generation is not None and not is_current_worker(project_id, worker_generation):
            raise RuntimeError("审图线程代际已过期，放弃执行")

        _check_cancel(project_id)
        _finalize_run(
            project_id,
            audit_version,
            status="running",
            current_step="主审准备基础数据",
            progress=5,
            total_issues=0,
            error=None,
            finished=False,
        )
        _event(
            project_id,
            audit_version,
            step_key="prepare",
            progress_hint=5,
            message="新审图内核启动：程序优先解析 + LLM边界介入",
            meta={"allow_incomplete": bool(allow_incomplete), "prompt_source": "program_first"},
        )

        rows = _list_ready_json_rows(project_id, allow_incomplete)
        existing_paths: list[tuple[JsonData, str]] = []
        for row in rows:
            path = str(getattr(row, "json_path", "") or "").strip()
            if path and Path(path).exists():
                existing_paths.append((row, path))
        if not existing_paths:
            raise RuntimeError("没有可用的 JSON 输入，无法执行审图")

        _check_cancel(project_id)
        _finalize_run(
            project_id,
            audit_version,
            status="running",
            current_step="主审整理图纸上下文",
            progress=20,
            total_issues=0,
            error=None,
            finished=False,
        )
        _event(
            project_id,
            audit_version,
            step_key="context",
            progress_hint=20,
            message=f"已加载 {len(existing_paths)} 份图纸 JSON，开始编译四层 IR",
            meta={"prompt_source": "program_first"},
        )

        known_sheet_nos = {
            str(getattr(row, "sheet_no", "") or "").strip()
            for row, _ in existing_paths
            if str(getattr(row, "sheet_no", "") or "").strip()
        }
        drawing_register_entries: list[dict[str, Any]] = []
        for row, _ in existing_paths:
            row_sheet_no = str(getattr(row, "sheet_no", "") or "").strip()
            if not row_sheet_no:
                continue
            drawing_register_entries.append(
                {
                    "sheet_number": row_sheet_no,
                    "title": str(getattr(row, "layout_name", "") or "").strip() or row_sheet_no,
                    "document_id": str(getattr(row, "source_dwg", "") or "").strip() or None,
                    "sheet_type": "unknown",
                }
            )
        project_name = _load_project_name(project_id)
        all_issues: list[dict[str, Any]] = []
        ir_file_count = 0
        total_rows = len(existing_paths)

        for idx, (row, json_path) in enumerate(existing_paths, start=1):
            _check_cancel(project_id)
            payload = _load_json_payload(json_path)
            if not payload:
                continue

            ir_package = compile_layout_ir(
                payload,
                source_json_path=json_path,
                known_sheet_nos=known_sheet_nos,
                project_id=project_id,
                project_name=project_name,
                drawing_register_entries=[
                    *drawing_register_entries,
                    {
                        "sheet_number": str(payload.get("sheet_no") or getattr(row, "sheet_no", "") or "").strip(),
                        "title": str(payload.get("sheet_name") or payload.get("layout_name") or "").strip(),
                        "document_id": str(payload.get("source_dwg") or "") or None,
                        "sheet_type": "unknown",
                    },
                ],
            )
            ir_path = persist_layout_ir(ir_package, source_json_path=json_path)
            ir_file_count += 1
            context_slices = build_context_slices(ir_package)

            weak_slice = find_slice_by_type(context_slices, "space_review")
            weak_trace = apply_weak_assist(ir_package, weak_slice)
            relation_slice = find_slice_by_type(context_slices, "relation_disambiguation")
            disambiguation_trace = disambiguate_reference_bindings(ir_package, relation_slice)

            issues = run_review_rules(ir_package, context_slices)
            issues = apply_confidence_propagation(issues, ir_package)
            issues = enforce_high_severity_constraint(issues)
            report_slice = build_report_context_slice(ir_package, issues)
            report_trace = polish_issue_writing(issues, report_slice)
            all_issues.extend(issues)

            progress = min(78, 20 + int((idx / max(total_rows, 1)) * 58))
            _finalize_run(
                project_id,
                audit_version,
                status="running",
                current_step="主审派发副审任务",
                progress=progress,
                total_issues=len(all_issues),
                error=None,
                finished=False,
            )
            _event(
                project_id,
                audit_version,
                step_key="task_planning",
                progress_hint=progress,
                message=f"已完成 IR 与规则处理 {idx}/{total_rows}：{Path(json_path).name}",
                meta={
                    "sheet_no": str(getattr(row, "sheet_no", "") or ""),
                    "ir_path": ir_path,
                    "issue_count": len(issues),
                    "weak_assist": weak_trace,
                    "disambiguation": disambiguation_trace,
                    "report_writing": report_trace,
                    "prompt_source": (
                        "llm_disambiguation"
                        if disambiguation_trace.get("llm_used")
                        else "program_first"
                    ),
                },
            )

        _check_cancel(project_id)
        _finalize_run(
            project_id,
            audit_version,
            status="running",
            current_step="主审复核冲突结果",
            progress=86,
            total_issues=len(all_issues),
            error=None,
            finished=False,
        )
        _event(
            project_id,
            audit_version,
            step_key="chief_review",
            progress_hint=86,
            message=f"规则执行完成：共发现 {len(all_issues)} 条问题",
            meta={"ir_file_count": ir_file_count, "prompt_source": "rule_engine"},
        )

        inserted_issue_ids = _persist_issues(project_id, audit_version, all_issues)
        issue_count = len(inserted_issue_ids)
        append_result_upsert_events(project_id, audit_version, issue_ids=inserted_issue_ids)
        append_result_summary_event(project_id, audit_version)

        _finalize_run(
            project_id,
            audit_version,
            status="running",
            current_step="主审完成结果收束",
            progress=95,
            total_issues=issue_count,
            error=None,
            finished=False,
        )
        _event(
            project_id,
            audit_version,
            step_key="report",
            progress_hint=95,
            message=f"结果落库完成：输出 {issue_count} 条问题",
            level="success",
            meta={"prompt_source": "report_writer"},
        )

        _finalize_run(
            project_id,
            audit_version,
            status="done",
            current_step="主审完成结果收束",
            progress=100,
            total_issues=issue_count,
            error=None,
            finished=True,
        )
        _event(
            project_id,
            audit_version,
            step_key="done",
            progress_hint=100,
            message="新审图内核执行完成",
            level="success",
            meta={"finished_at": datetime.now().isoformat(), "prompt_source": "program_first"},
        )
    except AuditCancellationRequested as exc:
        logger.warning("审图任务被中断: project=%s version=%s", project_id, audit_version)
        _finalize_run(
            project_id,
            audit_version,
            status="stopping",
            current_step="主审流程已中断",
            progress=0,
            total_issues=issue_count,
            error=str(exc),
            finished=True,
        )
        _event(
            project_id,
            audit_version,
            step_key="done",
            progress_hint=0,
            message="收到停止请求，任务已中断",
            level="warning",
            meta={"prompt_source": "program_first"},
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("新审图内核执行失败: project=%s version=%s", project_id, audit_version)
        _finalize_run(
            project_id,
            audit_version,
            status="failed",
            current_step="主审流程失败",
            progress=0,
            total_issues=issue_count,
            error=str(exc),
            finished=True,
        )
        _event(
            project_id,
            audit_version,
            step_key="done",
            progress_hint=0,
            message=f"执行失败：{exc}",
            level="error",
            meta={"prompt_source": "program_first"},
        )
    finally:
        clear_cancel_request(project_id)
        if clear_running is not None:
            clear_running(project_id)
