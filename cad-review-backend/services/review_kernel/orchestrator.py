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
from services.review_kernel.layout_contract import ensure_layout_json_contract
from services.review_kernel.llm_intervention import (
    apply_weak_assist,
    disambiguate_reference_bindings,
    get_llm_stage_switch_snapshot,
    polish_issue_writing,
)
from services.review_kernel.policy import load_project_policy
from services.review_kernel.rule_engine import run_review_rules
from services.review_kernel.rule_engine import run_cross_sheet_consistency_rules

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
        dispatch_observer=False,
    )


def _load_json_payload(path: str) -> Optional[dict[str, Any]]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        logger.exception("读取 JSON 失败: %s", path)
        return None
    return payload if isinstance(payload, dict) else None


def _persist_json_payload(path: str, payload: dict[str, Any]) -> None:
    Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


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
    if raw in {"dimension", "annotation_missing", "clearance_violation"}:
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


def _safe_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_global_pct(value: Any) -> Optional[dict[str, float]]:
    if not isinstance(value, dict):
        return None
    x = _safe_float(value.get("x"))
    y = _safe_float(value.get("y"))
    if x is None or y is None:
        return None
    return {
        "x": round(max(0.0, min(100.0, x)), 1),
        "y": round(max(0.0, min(100.0, y)), 1),
    }


def _normalize_layout_point(value: Any) -> Optional[dict[str, float]]:
    if isinstance(value, dict):
        x = _safe_float(value.get("x"))
        y = _safe_float(value.get("y"))
    elif isinstance(value, (list, tuple)) and len(value) >= 2:
        x = _safe_float(value[0])
        y = _safe_float(value[1])
    else:
        return None
    if x is None or y is None:
        return None
    return {"x": round(x, 3), "y": round(y, 3)}


def _normalize_layout_bbox(value: Any) -> Optional[list[float]]:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    x1 = _safe_float(value[0])
    y1 = _safe_float(value[1])
    x2 = _safe_float(value[2])
    y2 = _safe_float(value[3])
    if x1 is None or y1 is None or x2 is None or y2 is None:
        return None
    left, right = sorted((x1, x2))
    bottom, top = sorted((y1, y2))
    if right <= left or top <= bottom:
        return None
    return [round(left, 3), round(bottom, 3), round(right, 3), round(top, 3)]


def _center_from_location(location: dict[str, Any]) -> Optional[dict[str, float]]:
    center = _normalize_layout_point(location.get("center_canonical"))
    if center:
        return center
    bbox = _normalize_layout_bbox(location.get("bbox_canonical"))
    if not bbox:
        return None
    return {
        "x": round((bbox[0] + bbox[2]) / 2.0, 3),
        "y": round((bbox[1] + bbox[3]) / 2.0, 3),
    }


def _normalize_anchor(anchor: Any) -> Optional[dict[str, Any]]:
    if not isinstance(anchor, dict):
        return None
    role = str(anchor.get("role") or "source").strip() or "source"
    sheet_no = str(anchor.get("sheet_no") or "").strip()
    if not sheet_no:
        return None

    normalized: dict[str, Any] = {
        "role": role,
        "sheet_no": sheet_no,
        "origin": str(anchor.get("origin") or "review_kernel").strip() or "review_kernel",
    }

    grid = str(anchor.get("grid") or "").strip()
    if grid:
        normalized["grid"] = grid

    global_pct = _normalize_global_pct(anchor.get("global_pct"))
    if global_pct:
        normalized["global_pct"] = global_pct

    layout_point = _normalize_layout_point(anchor.get("layout_point"))
    if layout_point:
        normalized["layout_point"] = layout_point

    layout_bbox = _normalize_layout_bbox(anchor.get("layout_bbox"))
    if layout_bbox is None:
        layout_bbox = _normalize_layout_bbox(anchor.get("bbox_canonical"))
    if layout_bbox:
        normalized["layout_bbox"] = layout_bbox

    confidence = _safe_float(anchor.get("confidence"))
    if confidence is not None:
        normalized["confidence"] = round(max(0.0, min(1.0, confidence)), 3)

    if isinstance(anchor.get("highlight_region"), dict):
        normalized["highlight_region"] = anchor.get("highlight_region")

    passthrough_keys = {
        "role",
        "sheet_no",
        "origin",
        "grid",
        "global_pct",
        "layout_point",
        "layout_bbox",
        "bbox_canonical",
        "confidence",
        "highlight_region",
    }
    for key, value in anchor.items():
        if key in passthrough_keys or value is None:
            continue
        normalized[key] = value

    if "global_pct" not in normalized and "layout_point" not in normalized and "grid" not in normalized:
        return None
    return normalized


def _build_generated_anchor(
    *,
    role: str,
    sheet_no: str,
    location: dict[str, Any],
    confidence: Any,
    origin: str,
) -> Optional[dict[str, Any]]:
    sheet = str(sheet_no or "").strip()
    if not sheet:
        return None

    anchor: dict[str, Any] = {
        "role": role,
        "sheet_no": sheet,
        "origin": origin,
    }
    layout_point = _center_from_location(location)
    layout_bbox = _normalize_layout_bbox(location.get("bbox_canonical"))
    if layout_point:
        anchor["layout_point"] = layout_point
    if layout_bbox:
        anchor["layout_bbox"] = layout_bbox

    raw_confidence = _safe_float(confidence)
    if not layout_point:
        anchor["global_pct"] = {"x": 50.0, "y": 50.0}
        anchor["anchor_granularity"] = "sheet"
        anchor["origin"] = "sheet_center_fallback"
        if raw_confidence is not None:
            raw_confidence = min(raw_confidence, 0.35)

    if raw_confidence is not None:
        anchor["confidence"] = round(max(0.0, min(1.0, raw_confidence)), 3)
    return anchor


def _anchor_key(anchor: dict[str, Any]) -> tuple[Any, ...]:
    global_pct = anchor.get("global_pct") if isinstance(anchor.get("global_pct"), dict) else {}
    layout_point = anchor.get("layout_point") if isinstance(anchor.get("layout_point"), dict) else {}
    return (
        str(anchor.get("role") or "").strip(),
        str(anchor.get("sheet_no") or "").strip(),
        str(anchor.get("grid") or "").strip(),
        round(_safe_float(global_pct.get("x")) or -1.0, 3),
        round(_safe_float(global_pct.get("y")) or -1.0, 3),
        round(_safe_float(layout_point.get("x")) or -1.0, 3),
        round(_safe_float(layout_point.get("y")) or -1.0, 3),
    )


def _build_issue_anchors(issue: dict[str, Any]) -> list[dict[str, Any]]:
    location = issue.get("location") if isinstance(issue.get("location"), dict) else {}
    evidence = issue.get("evidence") if isinstance(issue.get("evidence"), dict) else {}

    anchors: list[dict[str, Any]] = []
    existing = issue.get("anchors")
    if isinstance(existing, list):
        for item in existing:
            normalized = _normalize_anchor(item)
            if normalized:
                anchors.append(normalized)

    existing_roles = {str(item.get("role") or "").strip() for item in anchors}
    source_sheet_no = str(location.get("sheet_no") or "").strip()
    if source_sheet_no and "source" not in existing_roles:
        generated_source = _build_generated_anchor(
            role="source",
            sheet_no=source_sheet_no,
            location=location,
            confidence=issue.get("confidence"),
            origin="rule_location",
        )
        if generated_source:
            anchors.append(generated_source)

    target_sheet_no = str(evidence.get("target_sheet_no") or "").strip()
    if target_sheet_no and "target" not in existing_roles:
        generated_target = _build_generated_anchor(
            role="target",
            sheet_no=target_sheet_no,
            location={},
            confidence=issue.get("confidence"),
            origin="target_sheet_reference",
        )
        if generated_target:
            anchors.append(generated_target)

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for anchor in anchors:
        key = _anchor_key(anchor)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(anchor)
    return deduped


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
            issue_payload = dict(issue)
            anchors = _build_issue_anchors(issue_payload)
            if anchors:
                issue_payload["anchors"] = anchors
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
                value_a=str(evidence.get("display_value") or evidence.get("value") or "") or None,
                value_b=str(evidence.get("required_value") or evidence.get("target_sheet_no") or "") or None,
                rule_id=str(issue.get("rule_id") or "") or None,
                finding_type=str(issue.get("category") or "") or None,
                finding_status=finding_status,
                source_agent="review_kernel",
                triggered_by="review_kernel_rule_engine",
                confidence=float(issue.get("confidence") or 0.0),
                description=str(issue.get("description") or "") or None,
                evidence_json=json.dumps(issue_payload, ensure_ascii=False),
            )
            inserted.append(row)
            db.add(row)
        db.commit()
        return [str(row.id) for row in inserted]
    finally:
        db.close()


def _issue_anchor_key(issue: dict[str, Any]) -> tuple[str, str, str]:
    location = issue.get("location") if isinstance(issue.get("location"), dict) else {}
    evidence = issue.get("evidence") if isinstance(issue.get("evidence"), dict) else {}

    primary_object_id = str(evidence.get("primary_object_id") or "").strip()
    dimension_evidence_id = str(evidence.get("dimension_evidence_id") or "").strip()
    if primary_object_id:
        anchor = f"obj:{primary_object_id}"
    elif dimension_evidence_id:
        anchor = f"dim:{dimension_evidence_id}"
    else:
        sheet_no = str(location.get("sheet_no") or "").strip()
        grid = str(location.get("grid") or "").strip()
        bbox = _normalize_layout_bbox(location.get("bbox_canonical"))
        if bbox:
            anchor = f"bbox:{sheet_no}:{grid}:{','.join(str(v) for v in bbox)}"
        else:
            center = _normalize_layout_point(location.get("center_canonical"))
            if center:
                anchor = f"pt:{sheet_no}:{grid}:{center['x']},{center['y']}"
            else:
                anchor = f"sheet:{sheet_no}:{grid}"

    space_id = (
        str(location.get("logical_sheet_id") or "").strip()
        or str(issue.get("target_space_id") or "").strip()
        or "unknown_space"
    )
    rule_id = str(issue.get("rule_id") or "").strip() or "unknown_rule"
    return space_id, rule_id, anchor


def _deduplicate_issues(issues: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        key = _issue_anchor_key(issue)
        groups.setdefault(key, []).append(issue)

    deduped: list[dict[str, Any]] = []
    removed = 0
    for key, bucket in groups.items():
        if not bucket:
            continue
        if len(bucket) == 1:
            issue = bucket[0]
            issue["anchor_key"] = key[2]
            deduped.append(issue)
            continue
        removed += len(bucket) - 1
        best = max(bucket, key=lambda item: float(item.get("confidence") or 0.0))
        evidence_refs: set[str] = set()
        for item in bucket:
            refs = item.get("evidence_refs")
            if isinstance(refs, list):
                evidence_refs.update(str(ref) for ref in refs if str(ref).strip())
        if evidence_refs:
            best["evidence_refs"] = sorted(evidence_refs)
        best["anchor_key"] = key[2]
        deduped.append(best)
    return deduped, removed


def _build_quality_metrics(
    *,
    total_rows: int,
    ir_file_count: int,
    issues: list[dict[str, Any]],
) -> dict[str, Any]:
    locatable = 0
    cross_sheet_index = 0
    cross_sheet_material = 0
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        location = issue.get("location") if isinstance(issue.get("location"), dict) else {}
        bbox = _normalize_layout_bbox(location.get("bbox_canonical"))
        center = _normalize_layout_point(location.get("center_canonical"))
        grid = str(location.get("grid") or "").strip()
        if bbox or center or grid:
            locatable += 1

        rule_id = str(issue.get("rule_id") or "").strip().upper()
        category = str(issue.get("category") or "").strip().lower()
        if rule_id.startswith("R-REF-"):
            cross_sheet_index += 1
        if rule_id.startswith("R-MAT-") and category in {"material_mismatch", "material_missing"}:
            cross_sheet_material += 1

    json_completeness_rate = round((ir_file_count / max(total_rows, 1)) * 100.0, 1)
    issue_locatable_rate = round((locatable / max(len(issues), 1)) * 100.0, 1)
    return {
        "json_completeness_rate_pct": json_completeness_rate,
        "issue_locatable_rate_pct": issue_locatable_rate,
        "cross_sheet_index_issue_count": cross_sheet_index,
        "cross_sheet_material_issue_count": cross_sheet_material,
    }


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
        policy = load_project_policy()

        if is_current_worker and worker_generation is not None and not is_current_worker(project_id, worker_generation):
            raise RuntimeError("审图线程代际已过期，放弃执行")

        _check_cancel(project_id)
        _finalize_run(
            project_id,
            audit_version,
            status="running",
            current_step="审图内核准备基础数据",
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
            meta={
                "allow_incomplete": bool(allow_incomplete),
                "prompt_source": "program_first",
                "llm_switches": get_llm_stage_switch_snapshot(),
                "project_policy": policy.to_snapshot(),
            },
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
            current_step="审图内核整理图纸上下文",
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
            meta={
                "prompt_source": "program_first",
                "max_concurrent_workers": policy.max_concurrent_workers,
                "rate_limit_retry_max": policy.rate_limit_retry_max,
            },
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
        ir_packages: list[dict[str, Any]] = []
        ir_file_count = 0
        contract_upgrade_count = 0
        total_rows = len(existing_paths)

        for idx, (row, json_path) in enumerate(existing_paths, start=1):
            _check_cancel(project_id)
            payload = _load_json_payload(json_path)
            if not payload:
                continue
            payload, upgraded, changed_fields = ensure_layout_json_contract(payload)
            if upgraded:
                _persist_json_payload(json_path, payload)
                contract_upgrade_count += 1
                logger.info(
                    "布局JSON合同已补齐: project=%s version=%s sheet=%s fields=%s",
                    project_id,
                    audit_version,
                    str(getattr(row, "sheet_no", "") or ""),
                    ",".join(changed_fields),
                )

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
            if policy.report_scope == "spaces_with_candidate_issues_only" and not issues:
                report_trace = {
                    "llm_used": False,
                    "allowed": False,
                    "reason": "report_scope_skip_empty_issues",
                    "updated": 0,
                }
            else:
                report_slice = build_report_context_slice(ir_package, issues)
                report_trace = polish_issue_writing(issues, report_slice)
            all_issues.extend(issues)
            ir_packages.append(ir_package)

            progress = min(78, 20 + int((idx / max(total_rows, 1)) * 58))
            _finalize_run(
                project_id,
                audit_version,
                status="running",
                current_step="审图内核分发复核任务",
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

        project_cross_sheet_issues = run_cross_sheet_consistency_rules(ir_packages)
        all_issues.extend(project_cross_sheet_issues)
        deduped_issues, dedup_removed_count = _deduplicate_issues(all_issues)
        quality_metrics = _build_quality_metrics(
            total_rows=total_rows,
            ir_file_count=ir_file_count,
            issues=deduped_issues,
        )

        _check_cancel(project_id)
        _finalize_run(
            project_id,
            audit_version,
            status="running",
            current_step="审图内核汇总规则结果",
            progress=86,
            total_issues=len(deduped_issues),
            error=None,
            finished=False,
        )
        _event(
            project_id,
            audit_version,
            step_key="kernel_review",
            progress_hint=86,
            message=f"规则执行完成：共发现 {len(deduped_issues)} 条问题",
            meta={
                "ir_file_count": ir_file_count,
                "layout_contract_upgraded_count": contract_upgrade_count,
                "cross_sheet_deep_check_issue_count": len(project_cross_sheet_issues),
                "dedup_removed_count": dedup_removed_count,
                **quality_metrics,
                "prompt_source": "rule_engine",
            },
        )

        inserted_issue_ids = _persist_issues(project_id, audit_version, deduped_issues)
        issue_count = len(inserted_issue_ids)
        append_result_upsert_events(project_id, audit_version, issue_ids=inserted_issue_ids)
        append_result_summary_event(project_id, audit_version)

        _finalize_run(
            project_id,
            audit_version,
            status="running",
            current_step="审图内核完成结果收束",
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
            current_step="审图内核完成结果收束",
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
            current_step="审图内核流程已中断",
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
            current_step="审图内核流程失败",
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
