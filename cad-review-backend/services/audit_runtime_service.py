"""
审核运行时服务
提供异步审核任务启动、进度查询、运行状态管理能力。
审核流水线执行逻辑统一由 services.review_kernel.orchestrator 提供。
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
import re
from typing import Any, Dict, List, Optional

from database import SessionLocal
from sqlalchemy import func

from models import AuditResult, AuditRun, AuditRunEvent, AuditTask, ProjectMemoryRecord
from services.audit_runtime.providers.factory import normalize_provider_mode

_running_lock = threading.Lock()
_running_projects: set[str] = set()
_running_workers: dict[str, threading.Thread] = {}
_worker_generations: dict[str, int] = {}
logger = logging.getLogger(__name__)

_PLANNING_STEP_TITLES = {
    "prepare": "审图内核准备基础数据",
    "context": "审图内核整理图纸上下文",
    "relationship_discovery": "副审整理候选关系",
    "task_planning": "审图内核分发复核任务",
    "chief_prompt": "审图内核装配审图资源",
    "chief_planning": "审图内核分发复核任务",
    "chief_review": "审图内核汇总规则结果",
    "kernel_review": "审图内核汇总规则结果",
    "report": "审图内核收束审核结果",
    "done": "审图内核完成结果收束",
}

_TASK_STAGE_TITLES = {
    "chief_prepare": "审图内核准备基础数据",
    "chief_context": "审图内核整理图纸上下文",
    "chief_prompt_ready": "审图内核装配审图资源",
    "worker_task_planning": "审图内核分发复核任务",
    "worker_relationship_discovery": "节点归属 Skill 整理候选关系",
    "worker_relationship_review": "节点归属 Skill 复核候选关系",
    "worker_skill_execution": "副审 Skill 执行任务",
    "worker_single_sheet_semantic": "尺寸一致性 Skill 提取单图语义",
    "worker_pair_compare": "尺寸一致性 Skill 执行双图对比",
    "chief_recheck": "审图内核复核副审分歧",
    "finding_synthesized": "审图内核汇总审图结论",
}

_SKILL_STAGE_TITLES = {
    ("node_host_binding", "worker_relationship_discovery"): "节点归属 Skill 整理候选关系",
    ("node_host_binding", "worker_relationship_review"): "节点归属 Skill 复核候选关系",
    ("node_host_binding", "worker_skill_execution"): "节点归属 Skill 执行复核",
    ("index_reference", "worker_skill_execution"): "索引引用 Skill 执行复核",
    ("material_semantic_consistency", "worker_skill_execution"): "材料语义一致性 Skill 执行复核",
    ("elevation_consistency", "worker_skill_execution"): "标高一致性 Skill 执行复核",
    ("elevation_consistency", "worker_single_sheet_semantic"): "标高一致性 Skill 提取单图语义",
    ("elevation_consistency", "worker_pair_compare"): "标高一致性 Skill 执行双图对比",
    ("spatial_consistency", "worker_skill_execution"): "空间一致性 Skill 执行复核",
    ("spatial_consistency", "worker_single_sheet_semantic"): "空间一致性 Skill 提取单图语义",
    ("spatial_consistency", "worker_pair_compare"): "空间一致性 Skill 执行双图对比",
}

_RUN_STEP_TO_TASK_STAGE = {
    "等待主审启动": "chief_prepare",
    "等待审图内核启动": "chief_prepare",
    "主审准备基础数据": "chief_prepare",
    "审图内核准备基础数据": "chief_prepare",
    "主审整理图纸上下文": "chief_context",
    "审图内核整理图纸上下文": "chief_context",
    "主审派发副审任务": "worker_task_planning",
    "审图内核分发复核任务": "worker_task_planning",
    "主审复核冲突结果": "chief_recheck",
    "审图内核汇总规则结果": "chief_recheck",
    "主审完成结果收束": "finding_synthesized",
    "审图内核完成结果收束": "finding_synthesized",
    "主审恢复中": "chief_recovery",
    "审图内核恢复中": "chief_recovery",
    "主审流程已中断": "runtime_interrupted",
    "审图内核流程已中断": "runtime_interrupted",
    "主审流程失败": "runtime_failed",
    "审图内核流程失败": "runtime_failed",
}

_RAW_PROCESS_EVENT_KINDS = {"model_stream_delta", "provider_stream_delta"}
_WORKER_SKILL_LABELS = {
    "index_reference": "索引引用 Skill",
    "material_semantic_consistency": "材料语义一致性 Skill",
    "node_host_binding": "节点归属 Skill",
    "spatial_consistency": "空间一致性 Skill",
    "elevation_consistency": "标高一致性 Skill",
}
_WORKER_NAME_LABELS = {
    "index_reference": "索引副审",
    "material_semantic_consistency": "材料副审",
    "node_host_binding": "节点归属副审",
    "spatial_consistency": "空间副审",
    "elevation_consistency": "标高副审",
}
_WORKER_BLOCKED_EVENT_KINDS = {"runner_turn_deferred", "runner_session_failed", "runner_turn_cancelled"}
_WORKER_COMPLETED_EVENT_KINDS = {"raw_output_saved", "output_repair_succeeded", "worker_assignment_completed"}
_MEANINGFUL_ACTION_LABELS = {
    "runner_turn_started": "调用 Skill",
    "runner_broadcast": "现场播报",
    "raw_output_saved": "保存输出",
    "output_validation_failed": "输出校验",
    "output_repair_started": "整理输出",
    "output_repair_succeeded": "整理完成",
    "runner_turn_deferred": "等待重试",
    "runner_session_failed": "执行失败",
    "runner_turn_cancelled": "已中断",
    "worker_assignment_completed": "任务完成",
}
_ACTION_PRIORITY = {
    "runner_session_started": 0,
    "runner_turn_started": 1,
    "runner_broadcast": 3,
    "output_validation_failed": 3,
    "output_repair_started": 3,
    "output_repair_succeeded": 4,
    "raw_output_saved": 4,
    "worker_assignment_completed": 4,
    "runner_turn_deferred": 5,
    "runner_session_failed": 5,
    "runner_turn_cancelled": 5,
}


def _as_text(value: object) -> str:
    return str(value or "").strip()


def _parse_event_meta(row: AuditRunEvent) -> Dict[str, Any]:
    if not row.meta_json:
        return {}
    try:
        payload = json.loads(row.meta_json)
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _is_chief_event(row: AuditRunEvent, meta: Dict[str, Any]) -> bool:
    actor_role = _as_text(meta.get("actor_role"))
    if actor_role == "chief":
        return True
    if actor_role == "worker":
        return False
    agent_key = _as_text(getattr(row, "agent_key", None))
    agent_name = _as_text(getattr(row, "agent_name", None))
    agent_id = _as_text(meta.get("agent_id"))
    message = _as_text(getattr(row, "message", None))
    return (
        "chief" in agent_key
        or "kernel" in agent_key
        or agent_id == "chief_review"
        or "主审" in agent_name
        or "审图内核" in agent_name
        or message.startswith("主审 Agent")
        or message.startswith("审图内核 Agent")
    )


def _parse_count_from_event_messages(rows: List[AuditRunEvent], pattern: str) -> int:
    compiled = re.compile(pattern)
    for row in reversed(rows):
        match = compiled.search(_as_text(getattr(row, "message", None)))
        if match:
            try:
                return int(match.group(1))
            except (TypeError, ValueError):
                return 0
    return 0


def _resolve_skill_id(row: AuditRunEvent, meta: Dict[str, Any]) -> str:
    direct = _as_text(meta.get("skill_id") or meta.get("worker_kind") or meta.get("suggested_worker_kind"))
    if direct:
        return direct
    session_key = _as_text(meta.get("session_key"))
    if session_key.startswith("worker_skill:"):
        parts = session_key.split(":")
        if len(parts) >= 2:
            return _as_text(parts[1])
    turn_kind = _as_text(meta.get("turn_kind"))
    agent_name = _as_text(getattr(row, "agent_name", None))
    if turn_kind == "dimension_sheet_semantic":
        return "elevation_consistency"
    if turn_kind == "dimension_pair_compare":
        return "spatial_consistency"
    if turn_kind == "relationship_candidate_review":
        return "node_host_binding"
    if "index" in turn_kind or "索引" in agent_name:
        return "index_reference"
    if "material" in turn_kind or "材料" in agent_name:
        return "material_semantic_consistency"
    if "关系" in agent_name:
        return "node_host_binding"
    if "尺寸" in agent_name:
        return "spatial_consistency"
    return ""


def _extract_session_key(row: AuditRunEvent, meta: Dict[str, Any]) -> str:
    session_key = _as_text(meta.get("session_key"))
    if session_key:
        return session_key

    artifact_path = _as_text(meta.get("artifact_path"))
    file_name = artifact_path.rsplit("/", 1)[-1]
    if not file_name:
        return ""

    sheet_match = re.search(r"sheet_semantic_([^_]+)__\d{8}", file_name)
    if sheet_match:
        return f"sheet_semantic:{sheet_match.group(1)}"

    pair_match = re.search(r"pair_compare_([^_]+)_([^_]+)__\d{8}", file_name)
    if pair_match:
        return f"pair_compare:{pair_match.group(1)}:{pair_match.group(2)}"

    candidate_match = re.search(r"candidate_review_([^_]+)__\d{8}", file_name)
    if candidate_match:
        return f"candidate_review:{candidate_match.group(1)}"
    return ""


def _resolve_visible_session_key(meta: Dict[str, Any], session_key: str) -> str:
    visible = _as_text(meta.get("visible_session_key"))
    if visible:
        return visible
    assignment_id = _as_text(meta.get("assignment_id"))
    if assignment_id:
        return f"assignment:{assignment_id}"
    return session_key


def _extract_session_tail(session_key: str) -> List[str]:
    normalized = _as_text(session_key)
    if not normalized:
        return []
    parts = normalized.split(":")
    if normalized.startswith("worker_skill:"):
        return parts
    if len(parts) >= 5:
        return parts[3:]
    return parts


def _extract_task_title(row: AuditRunEvent, meta: Dict[str, Any], session_key: str) -> str:
    source_sheet = _as_text(meta.get("source_sheet_no") or meta.get("candidate_source_sheet_no"))
    target_sheet = _as_text(meta.get("target_sheet_no") or meta.get("candidate_target_sheet_no"))
    sheet_no = _as_text(meta.get("sheet_no"))
    if source_sheet and target_sheet:
        return f"{source_sheet} ↔ {target_sheet}"
    if sheet_no:
        return f"图纸 {sheet_no}"

    tail = _extract_session_tail(session_key)

    if session_key.startswith("worker_skill:"):
        _, _, source, targets = (session_key.split(":") + ["", "", "", ""])[:4]
        if source and targets and targets != "SELF":
            return f"{source} ↔ {targets.replace('__', ' / ')}"
        if source:
            return f"图纸 {source}"
    if tail[:1] in (["sheet_semantic"], ["dimension_sheet_semantic"]) and len(tail) >= 2:
        return f"图纸 {tail[1]}"
    if tail[:1] in (["pair_compare"], ["dimension_pair_compare"]) and len(tail) >= 3:
        return f"{tail[1]} ↔ {tail[2]}"
    if tail[:1] in (["candidate_review"], ["relationship_candidate_review"]) and len(tail) >= 2:
        return f"候选关系 {tail[1][:8]}"
    if session_key.startswith("sheet_semantic:"):
        value = _as_text(session_key.split(":", 1)[1] if ":" in session_key else "")
        return f"图纸 {value}" if value else "单图语义"
    if session_key.startswith("pair_compare:"):
        parts = session_key.split(":")
        if len(parts) >= 3 and parts[1] and parts[2]:
            return f"{parts[1]} ↔ {parts[2]}"
        return "跨图尺寸"
    if session_key.startswith("candidate_review:"):
        value = _as_text(session_key.split(":", 1)[1] if ":" in session_key else "")
        return f"候选关系 {value[:8]}" if value else "候选关系复核"

    sheets = re.findall(r"[A-Z]{1,2}\d{3,4}[A-Z]?", _as_text(getattr(row, "message", None)))
    if len(sheets) >= 2:
        return f"{sheets[0]} ↔ {sheets[1]}"
    if len(sheets) == 1:
        return f"图纸 {sheets[0]}"
    return "副审任务"


def _resolve_worker_name(row: AuditRunEvent, skill_id: str) -> str:
    if skill_id in _WORKER_NAME_LABELS:
        return _WORKER_NAME_LABELS[skill_id]
    agent_name = _as_text(getattr(row, "agent_name", None))
    if not agent_name:
        return "副审"
    return agent_name[:-5] if agent_name.endswith("Agent") else agent_name


def _resolve_skill_label(skill_id: str) -> str:
    return _WORKER_SKILL_LABELS.get(skill_id, "通用复核 Skill")


def _resolve_worker_current_action(row: AuditRunEvent, meta: Dict[str, Any], skill_id: str, task_title: str) -> str:
    event_kind = _as_text(getattr(row, "event_kind", None))
    raw_message = _as_text(getattr(row, "message", None))
    turn_kind = _as_text(meta.get("turn_kind"))

    if event_kind == "raw_output_saved":
        return "已收束并保存输出"
    if event_kind == "output_validation_failed":
        return "输出格式待整理"
    if event_kind == "output_repair_started":
        return "正在整理输出格式"
    if event_kind == "output_repair_succeeded":
        return "已整理成标准结果"
    if event_kind == "runner_turn_deferred":
        return "等待重试或审图内核介入"
    if event_kind == "runner_session_failed":
        return "执行失败，等待重试"
    if event_kind == "runner_turn_cancelled":
        return "已被人工中断"

    if event_kind == "runner_broadcast":
        if skill_id == "elevation_consistency":
            if "图纸" in task_title:
                return "正在抽取单图标高语义"
            if "↔" in task_title:
                return "正在比对跨图尺寸关系"
            return "正在推进标高复核"
        if skill_id == "spatial_consistency":
            return "正在比对跨图空间关系"
        if skill_id == "node_host_binding":
            return "正在复核节点归属"
        if skill_id == "index_reference":
            return "正在核对索引引用"
        if skill_id == "material_semantic_consistency":
            return "正在核对材料语义"
    if event_kind == "runner_turn_started":
        if turn_kind in {"dimension_sheet_semantic", "sheet_semantic"}:
            return "准备提取单图标高语义"
        if turn_kind in {"dimension_pair_compare", "pair_compare"}:
            return "准备执行跨图尺寸对比"
        if turn_kind in {"relationship_candidate_review", "candidate_review"}:
            return "准备复核候选关系"
        return "已启动本轮技能执行"
    if raw_message and "已通过 Runner 发起一次" not in raw_message:
        return raw_message
    return "正在执行副审任务"


def _build_action_entry(row: AuditRunEvent, meta: Dict[str, Any], skill_id: str, task_title: str) -> Dict[str, object]:
    event_kind = _as_text(getattr(row, "event_kind", None))
    return {
        "at": row.created_at.isoformat() if row.created_at else None,
        "label": _MEANINGFUL_ACTION_LABELS.get(event_kind, "现场更新"),
        "text": _resolve_worker_current_action(row, meta, skill_id, task_title),
    }


def _build_worker_context(meta: Dict[str, Any], session_key: str) -> Dict[str, Optional[str]]:
    source_sheet_no = _as_text(meta.get("source_sheet_no") or meta.get("candidate_source_sheet_no")) or None
    target_sheet_no = _as_text(meta.get("target_sheet_no") or meta.get("candidate_target_sheet_no")) or None
    sheet_no = _as_text(meta.get("sheet_no")) or None

    tail = _extract_session_tail(session_key)
    if not sheet_no and tail[:1] in (["sheet_semantic"], ["dimension_sheet_semantic"]) and len(tail) >= 2:
        sheet_no = tail[1]
    if not source_sheet_no and not target_sheet_no and tail[:1] in (["pair_compare"], ["dimension_pair_compare"]) and len(tail) >= 3:
        source_sheet_no = tail[1] or None
        target_sheet_no = tail[2] or None

    return {
        "source_sheet_no": source_sheet_no,
        "target_sheet_no": target_sheet_no,
        "sheet_no": sheet_no,
    }


def _merge_worker_context(
    current: Dict[str, Optional[str]] | None,
    incoming: Dict[str, Optional[str]],
) -> Dict[str, Optional[str]]:
    base = dict(current or {})
    for key, value in incoming.items():
        if value and not base.get(key):
            base[key] = value
    return {
        "source_sheet_no": base.get("source_sheet_no"),
        "target_sheet_no": base.get("target_sheet_no"),
        "sheet_no": base.get("sheet_no"),
    }


def _worker_group_signature(row: AuditRunEvent, skill_id: str) -> str:
    return "::".join(
        [
            _as_text(getattr(row, "agent_key", None)) or "unknown",
            _as_text(skill_id) or "unknown",
        ]
    )


def _resolve_worker_group_key(
    *,
    row: AuditRunEvent,
    meta: Dict[str, Any],
    session_key: str,
    skill_id: str,
    worker_sessions: Dict[str, Dict[str, object]],
) -> str:
    visible_key = _resolve_visible_session_key(meta, session_key)
    if visible_key != session_key:
        return visible_key
    signature = _worker_group_signature(row, skill_id)
    matched_keys = [
        key
        for key, item in worker_sessions.items()
        if bool(item.get("_has_assignment_identity")) and item.get("_signature") == signature
    ]
    if len(matched_keys) == 1:
        return matched_keys[0]
    return session_key


def _append_recent_action(
    state: Dict[str, object],
    action: Dict[str, object],
) -> None:
    recent_actions = list(state.get("recent_actions") or [])
    for last_action in recent_actions:
        if (
            str(last_action.get("label") or "") == str(action.get("label") or "")
            and str(last_action.get("text") or "") == str(action.get("text") or "")
        ):
            return
    recent_actions.append(action)
    state["recent_actions"] = recent_actions[-3:]


def _set_running(project_id: str) -> bool:
    with _running_lock:
        if project_id in _running_projects:
            return False
        _running_projects.add(project_id)
        _worker_generations.setdefault(project_id, 1)
        return True


def _clear_running(project_id: str, *, generation: int | None = None) -> None:
    with _running_lock:
        current_generation = _worker_generations.get(project_id)
        if generation is not None and current_generation is not None and generation != current_generation:
            return
        _running_projects.discard(project_id)
        _running_workers.pop(project_id, None)
        _worker_generations.pop(project_id, None)


def is_project_running(project_id: str) -> bool:
    with _running_lock:
        return project_id in _running_projects


def register_project_worker(project_id: str, worker: threading.Thread) -> None:
    with _running_lock:
        _running_workers[project_id] = worker


def register_project_worker_generation(project_id: str, generation: int) -> None:
    with _running_lock:
        _worker_generations[project_id] = int(generation)


def get_project_worker_generation(project_id: str) -> int:
    with _running_lock:
        return int(_worker_generations.get(project_id, 0))


def is_worker_generation_current(project_id: str, generation: int) -> bool:
    with _running_lock:
        return int(_worker_generations.get(project_id, 0)) == int(generation)


def bump_project_worker_generation(project_id: str) -> int:
    with _running_lock:
        next_generation = int(_worker_generations.get(project_id, 0)) + 1
        _worker_generations[project_id] = next_generation
        _running_projects.add(project_id)
        return next_generation


def wait_for_project_stop(project_id: str, timeout_seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + max(0.0, timeout_seconds)

    while time.monotonic() < deadline:
        with _running_lock:
            worker = _running_workers.get(project_id)
            running = project_id in _running_projects

        if worker is not None:
            remaining = max(0.0, deadline - time.monotonic())
            worker.join(min(0.2, remaining))
            if not worker.is_alive():
                return True
            continue

        if not running:
            return True

        time.sleep(0.1)

    with _running_lock:
        worker = _running_workers.get(project_id)
        running = project_id in _running_projects
    return (worker is None or not worker.is_alive()) and not running


def get_latest_run(project_id: str, db) -> Optional[AuditRun]:
    return (
        db.query(AuditRun)
        .filter(AuditRun.project_id == project_id)
        .order_by(AuditRun.audit_version.desc(), AuditRun.created_at.desc())
        .first()
    )


def get_next_audit_version(project_id: str, db) -> int:
    version_sources = (
        AuditRun,
        AuditResult,
        ProjectMemoryRecord,
        AuditRunEvent,
        AuditTask,
    )
    max_version = 0
    for model in version_sources:
        value = (
            db.query(func.max(model.audit_version))
            .filter(model.project_id == project_id)
            .scalar()
        )
        if isinstance(value, int):
            max_version = max(max_version, value)
    return max_version + 1


def _append_task_trace(task: AuditTask, payload: Dict[str, object]) -> None:
    if task.trace_json:
        try:
            trace = json.loads(task.trace_json)
            if not isinstance(trace, dict):
                trace = {"planner_raw": task.trace_json}
        except Exception:
            trace = {"planner_raw": task.trace_json}
    else:
        trace = {}

    runtime = trace.get("runtime")
    if not isinstance(runtime, list):
        runtime = []
    runtime.append(payload)
    trace["runtime"] = runtime[-30:]
    task.trace_json = json.dumps(trace, ensure_ascii=False)


def mark_stale_running_runs(project_id: str, db, reason: str = "任务已中断（服务重启或人工停止）") -> int:
    """将数据库中遗留的 running 记录标记为 failed，避免出现僵尸运行态。"""
    stale_runs = (
        db.query(AuditRun)
        .filter(
            AuditRun.project_id == project_id,
            AuditRun.status == "running",
        )
        .all()
    )
    if not stale_runs:
        return 0

    now = datetime.now()
    stale_versions = {run.audit_version for run in stale_runs}
    for run in stale_runs:
        run.status = "failed"
        run.current_step = "审图内核流程已中断"
        run.error = run.error or reason
        run.finished_at = run.finished_at or now
        run.updated_at = now

    stale_tasks = (
        db.query(AuditTask)
        .filter(
            AuditTask.project_id == project_id,
            AuditTask.audit_version.in_(stale_versions),
            AuditTask.status == "running",
        )
        .all()
    )
    for task in stale_tasks:
        task.status = "failed"
        _append_task_trace(
            task,
            {
                "at": now.isoformat(),
                "status": "failed",
                "note": "stale_run_recovered",
            },
        )

    db.commit()
    logger.warning(
        "project=%s stale running runs recovered: count=%s versions=%s",
        project_id,
        len(stale_runs),
        sorted(stale_versions),
    )
    return len(stale_runs)


def start_audit_async(
    project_id: str,
    audit_version: int,
    *,
    allow_incomplete: bool = False,
    provider_mode: Optional[str] = None,
    resume_existing: bool = False,
    worker_generation: Optional[int] = None,
) -> None:
    """启动后台审核线程（调用方需已持有 _set_running 锁）。"""
    from services.review_kernel.orchestrator import execute_pipeline

    generation = int(worker_generation or 0) or max(1, get_project_worker_generation(project_id))
    register_project_worker_generation(project_id, generation)

    worker = threading.Thread(
        target=execute_pipeline,
        args=(project_id, audit_version),
        kwargs={
            "allow_incomplete": allow_incomplete,
            "clear_running": lambda pid: _clear_running(pid, generation=generation),
            "resume_existing": resume_existing,
            "worker_generation": generation,
            "is_current_worker": is_worker_generation_current,
        },
        daemon=True,
    )
    register_project_worker(project_id, worker)
    worker.start()


def resolve_runtime_pipeline_mode() -> str:
    from services.review_kernel.orchestrator import resolve_pipeline_mode

    return resolve_pipeline_mode()


def restart_master_agent_async(project_id: str, audit_version: int) -> Dict[str, object]:
    db = SessionLocal()
    try:
        run = (
            db.query(AuditRun)
            .filter(
                AuditRun.project_id == project_id,
                AuditRun.audit_version == int(audit_version),
            )
            .first()
        )
        if not run:
            return {"restarted": False, "reason": "run_not_found"}
        run.status = "running"
        run.current_step = "审图内核恢复中"
        run.error = None
        run.updated_at = datetime.now()
        db.commit()
        provider_mode = normalize_provider_mode(getattr(run, "provider_mode", None))
        allow_incomplete = str(getattr(run, "scope_mode", "") or "").strip() == "partial"
    finally:
        db.close()

    generation = bump_project_worker_generation(project_id)
    start_audit_async(
        project_id,
        int(audit_version),
        allow_incomplete=allow_incomplete,
        provider_mode=provider_mode,
        resume_existing=True,
        worker_generation=generation,
    )
    return {
        "restarted": True,
        "generation": generation,
        "provider_mode": provider_mode,
        "resume_existing": True,
    }


def build_run_snapshot(run: Optional[AuditRun]) -> Dict[str, object]:
    pipeline_mode = resolve_runtime_pipeline_mode()
    planner_source = "review_kernel"
    prompt_source = "rule_engine"
    task_stage = _RUN_STEP_TO_TASK_STAGE.get(str(getattr(run, "current_step", "") or "").strip()) if run else None
    if not run:
        return {
            "audit_version": None,
            "status": "idle",
            "current_step": None,
            "progress": 0,
            "total_issues": 0,
            "pipeline_mode": pipeline_mode,
            "planner_source": planner_source,
            "task_stage": task_stage,
            "prompt_source": prompt_source,
            "skill_id": None,
            "skill_mode": None,
            "compat_mode": None,
            "session_key": None,
            "evidence_selection_policy": None,
            "error": None,
            "started_at": None,
            "finished_at": None,
            "scope_mode": None,
            "scope_summary": None,
        }

    return {
        "audit_version": run.audit_version,
        "status": run.status,
        "current_step": run.current_step,
        "progress": run.progress,
        "total_issues": run.total_issues,
        "pipeline_mode": pipeline_mode,
        "planner_source": planner_source,
        "task_stage": task_stage,
        "prompt_source": prompt_source,
        "skill_id": None,
        "skill_mode": None,
        "compat_mode": None,
        "session_key": None,
        "evidence_selection_policy": None,
        "provider_mode": normalize_provider_mode(getattr(run, "provider_mode", None)),
        "error": run.error,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "finished_at": run.finished_at.isoformat() if run.finished_at else None,
        "scope_mode": getattr(run, "scope_mode", None),
        "scope_summary": getattr(run, "scope_summary", None),
    }


def _resolve_planning_step_title(step_key: Optional[str]) -> Optional[str]:
    key = (step_key or "").strip().lower()
    if not key:
        return None
    return _PLANNING_STEP_TITLES.get(key)


def _resolve_task_stage_title(task_stage: object, skill_id: object) -> Optional[str]:
    normalized_stage = str(task_stage or "").strip()
    if not normalized_stage:
        return None
    normalized_skill = str(skill_id or "").strip()
    if normalized_skill:
        title = _SKILL_STAGE_TITLES.get((normalized_skill, normalized_stage))
        if title:
            return title
    return _TASK_STAGE_TITLES.get(normalized_stage)


def build_recent_event_snapshot(
    project_id: str,
    db,
    *,
    max_age_seconds: int = 900,
) -> Dict[str, object]:
    runtime_mode = resolve_runtime_pipeline_mode()
    latest_event = (
        db.query(AuditRunEvent)
        .filter(AuditRunEvent.project_id == project_id)
        .order_by(AuditRunEvent.created_at.desc(), AuditRunEvent.id.desc())
        .first()
    )
    if not latest_event:
        return build_run_snapshot(None)

    if latest_event.created_at and latest_event.created_at < datetime.now() - timedelta(seconds=max_age_seconds):
        return build_run_snapshot(None)

    meta: Dict[str, object] = {}
    if latest_event.meta_json:
        try:
            payload = json.loads(latest_event.meta_json)
            if isinstance(payload, dict):
                meta = payload
        except Exception:
            meta = {}

    provider_mode = normalize_provider_mode(meta.get("provider_mode") or meta.get("provider_name"))
    progress = latest_event.progress_hint
    if progress is None:
        progress = {
            "context": 10,
            "relationship_discovery": 12,
            "task_planning": 18,
        }.get((latest_event.step_key or "").strip().lower(), 8)

    current_step = (
        _resolve_task_stage_title(meta.get("task_stage"), meta.get("skill_id"))
        or _resolve_planning_step_title(latest_event.step_key)
        or latest_event.message
    )

    return {
        "audit_version": latest_event.audit_version,
        "status": "planning",
        "current_step": current_step,
        "progress": progress,
        "total_issues": 0,
        "pipeline_mode": runtime_mode,
        "planner_source": (
            "review_kernel"
            if runtime_mode == "review_kernel_v1"
            else str(meta.get("planner_source") or "").strip() or None
        ),
        "task_stage": str(meta.get("task_stage") or "").strip() or None,
        "prompt_source": str(meta.get("prompt_source") or "").strip() or None,
        "skill_id": str(meta.get("skill_id") or "").strip() or None,
        "skill_mode": str(meta.get("skill_mode") or "").strip() or None,
        "compat_mode": str(meta.get("compat_mode") or "").strip() or None,
        "session_key": str(meta.get("session_key") or "").strip() or None,
        "evidence_selection_policy": str(meta.get("evidence_selection_policy") or "").strip() or None,
        "provider_mode": provider_mode,
        "error": None,
        "started_at": latest_event.created_at.isoformat() if latest_event.created_at else None,
        "finished_at": None,
        "scope_mode": None,
        "scope_summary": None,
    }


def enrich_snapshot_from_latest_event(
    project_id: str,
    audit_version: Optional[int],
    snapshot: Dict[str, object],
    db,
) -> Dict[str, object]:
    runtime_mode = resolve_runtime_pipeline_mode()
    if audit_version is None:
        return snapshot

    latest_event = (
        db.query(AuditRunEvent)
        .filter(
            AuditRunEvent.project_id == project_id,
            AuditRunEvent.audit_version == audit_version,
        )
        .order_by(AuditRunEvent.created_at.desc(), AuditRunEvent.id.desc())
        .first()
    )
    if not latest_event or not latest_event.meta_json:
        return snapshot

    try:
        meta = json.loads(latest_event.meta_json)
        if not isinstance(meta, dict):
            return snapshot
    except Exception:
        return snapshot

    merged = dict(snapshot)
    for key in (
        "task_stage",
        "prompt_source",
        "skill_id",
        "skill_mode",
        "compat_mode",
        "session_key",
        "evidence_selection_policy",
    ):
        value = meta.get(key)
        if isinstance(value, str):
            value = value.strip() or None
        if value is not None:
            merged[key] = value
    merged["pipeline_mode"] = runtime_mode
    if runtime_mode == "review_kernel_v1":
        merged["planner_source"] = "review_kernel"
    elif not merged.get("planner_source"):
        planner_value = meta.get("planner_source")
        if isinstance(planner_value, str):
            merged["planner_source"] = planner_value.strip() or None
    stage_title = _resolve_task_stage_title(merged.get("task_stage"), merged.get("skill_id"))
    if stage_title:
        merged["current_step"] = stage_title
    return merged


def build_ui_runtime_snapshot(
    project_id: str,
    audit_version: Optional[int],
    snapshot: Dict[str, object],
    *,
    total_issues: int,
    db,
) -> Dict[str, object]:
    if audit_version is None:
        chief_action = _as_text(snapshot.get("current_step")) or "审图内核等待启动"
        return {
            "chief": {
                "title": "审图内核",
                "current_action": chief_action,
                "summary": "审图内核尚未分发复核任务。",
                "assigned_task_count": 0,
                "active_worker_count": 0,
                "completed_worker_count": 0,
                "blocked_worker_count": 0,
                "queued_task_count": 0,
                "issue_count": int(total_issues or 0),
                "updated_at": None,
            },
            "final_review": {
                "current_assignment_title": None,
                "current_action": "终审等待审图内核提交候选问题",
                "summary": "当前还没有进入终审环节。",
                "accepted_count": 0,
                "needs_more_evidence_count": 0,
                "redispatch_count": 0,
                "updated_at": None,
            },
            "organizer": {
                "current_action": "结构化整理未开始",
                "summary": "当前还没有可输出的问题。",
                "accepted_issue_count": 0,
                "current_section": None,
                "updated_at": None,
            },
            "worker_sessions": [],
            "recent_completed": [],
        }

    rows = (
        db.query(AuditRunEvent)
        .filter(
            AuditRunEvent.project_id == project_id,
            AuditRunEvent.audit_version == audit_version,
        )
        .order_by(AuditRunEvent.created_at.asc(), AuditRunEvent.id.asc())
        .all()
    )

    chief_rows: List[AuditRunEvent] = []
    final_review_rows: List[tuple[AuditRunEvent, Dict[str, Any]]] = []
    organizer_rows: List[tuple[AuditRunEvent, Dict[str, Any]]] = []
    worker_sessions: Dict[str, Dict[str, object]] = {}

    for row in rows:
        meta = _parse_event_meta(row)
        event_kind = _as_text(getattr(row, "event_kind", None))
        if event_kind == "final_review_decision":
            final_review_rows.append((row, meta))
        task_stage = _as_text(meta.get("task_stage"))
        if (
            task_stage == "organizer_converted"
            or (
                event_kind == "phase_completed"
                and ("organizer_markdown_length" in meta or "final_issues" in meta)
            )
            or event_kind == "result_summary"
        ):
            organizer_rows.append((row, meta))
        if _is_chief_event(row, meta):
            chief_rows.append(row)
            continue

        if event_kind in _RAW_PROCESS_EVENT_KINDS:
            continue

        session_key = _extract_session_key(row, meta)
        if not session_key:
            continue

        skill_id = _resolve_skill_id(row, meta)
        task_title = _extract_task_title(row, meta, session_key)
        group_key = _resolve_worker_group_key(
            row=row,
            meta=meta,
            session_key=session_key,
            skill_id=skill_id,
            worker_sessions=worker_sessions,
        )
        state = worker_sessions.get(group_key)
        if state is None:
            state = {
                "session_key": group_key,
                "worker_name": _resolve_worker_name(row, skill_id),
                "skill_id": skill_id or None,
                "skill_label": _resolve_skill_label(skill_id),
                "task_title": task_title,
                "current_action": _resolve_worker_current_action(row, meta, skill_id, task_title),
                "status": "active",
                "updated_at": row.created_at.isoformat() if row.created_at else None,
                "context": _build_worker_context(meta, session_key),
                "recent_actions": [],
                "_action_priority": _ACTION_PRIORITY.get(event_kind, 2),
                "_last_event_id": row.id,
                "_signature": _worker_group_signature(row, skill_id),
                "_has_assignment_identity": group_key != session_key or bool(_as_text(meta.get("assignment_id"))),
            }
            worker_sessions[group_key] = state

        if skill_id and not state.get("skill_id"):
            state["skill_id"] = skill_id
            state["skill_label"] = _resolve_skill_label(skill_id)
            state["worker_name"] = _resolve_worker_name(row, skill_id)
        if task_title and state.get("task_title") == "副审任务":
            state["task_title"] = task_title

        current_action = _resolve_worker_current_action(row, meta, skill_id, task_title)
        action_priority = _ACTION_PRIORITY.get(event_kind, 2)
        if int(state.get("_action_priority") or 0) <= action_priority:
            state["current_action"] = current_action
            state["_action_priority"] = action_priority
        state["updated_at"] = row.created_at.isoformat() if row.created_at else None
        state["context"] = _merge_worker_context(
            state.get("context") if isinstance(state.get("context"), dict) else None,
            _build_worker_context(meta, session_key),
        )
        state["_last_event_id"] = row.id
        if group_key != session_key or _as_text(meta.get("assignment_id")):
            state["_has_assignment_identity"] = True

        if event_kind in _WORKER_COMPLETED_EVENT_KINDS:
            state["status"] = "completed"
        elif event_kind in _WORKER_BLOCKED_EVENT_KINDS:
            state["status"] = "blocked"
        else:
            state["status"] = "active"

        action = _build_action_entry(row, meta, skill_id, task_title)
        _append_recent_action(state, action)

    worker_items = sorted(
        worker_sessions.values(),
        key=lambda item: (
            _as_text(item.get("updated_at")),
            int(item.get("_last_event_id") or 0),
        ),
        reverse=True,
    )
    active_items = [item for item in worker_items if item.get("status") in {"active", "blocked"}]
    completed_items = [item for item in worker_items if item.get("status") == "completed"][:6]

    assigned_task_count = (
        db.query(AuditTask)
        .filter(
            AuditTask.project_id == project_id,
            AuditTask.audit_version == audit_version,
        )
        .count()
    )
    if assigned_task_count == 0:
        assigned_task_count = _parse_count_from_event_messages(chief_rows, r"生成\s*(\d+)\s*张副审任务卡")

    hypothesis_count = _parse_count_from_event_messages(chief_rows, r"生成\s*(\d+)\s*条待核对怀疑卡")
    active_count = sum(1 for item in worker_items if item.get("status") == "active")
    completed_count = sum(1 for item in worker_items if item.get("status") == "completed")
    blocked_count = sum(1 for item in worker_items if item.get("status") == "blocked")
    queued_count = max(0, int(assigned_task_count or 0) - active_count - completed_count - blocked_count)

    latest_chief = chief_rows[-1] if chief_rows else None
    chief_current_action = _as_text(getattr(latest_chief, "message", None)) or _as_text(snapshot.get("current_step")) or "审图内核正在推进审图"
    summary_parts: List[str] = []
    if hypothesis_count > 0:
        summary_parts.append(f"已形成 {hypothesis_count} 条待核对怀疑卡")
    if assigned_task_count > 0:
        summary_parts.append(f"已派发 {assigned_task_count} 张副审任务卡")
    if active_count > 0:
        summary_parts.append(f"{active_count} 个副审进行中")
    if completed_count > 0:
        summary_parts.append(f"{completed_count} 个副审已完成")
    if blocked_count > 0:
        summary_parts.append(f"{blocked_count} 个副审待处理")
    if queued_count > 0:
        summary_parts.append(f"{queued_count} 张任务待启动")

    chief_updated_at = latest_chief.created_at.isoformat() if latest_chief and latest_chief.created_at else snapshot.get("started_at")

    accepted_count = 0
    needs_more_evidence_count = 0
    redispatch_count = 0
    current_assignment_title: Optional[str] = None
    final_review_current_action = "终审等待审图内核提交候选问题"
    final_review_updated_at: Optional[str] = None
    for row, meta in final_review_rows:
        decision = _as_text(meta.get("decision"))
        if decision == "accepted":
            accepted_count += 1
        elif decision == "needs_more_evidence":
            needs_more_evidence_count += 1
        elif decision == "redispatch":
            redispatch_count += 1
        if not current_assignment_title:
            current_assignment_title = (
                _as_text(meta.get("task_title"))
                or _as_text(meta.get("assignment_id"))
                or None
            )
    if final_review_rows:
        latest_final_review_row, latest_final_review_meta = final_review_rows[-1]
        final_review_current_action = (
            _as_text(getattr(latest_final_review_row, "message", None))
            or "终审正在处理审图内核提交的问题候选"
        )
        if not current_assignment_title:
            current_assignment_title = (
                _as_text(latest_final_review_meta.get("task_title"))
                or _as_text(latest_final_review_meta.get("assignment_id"))
                or None
            )
        final_review_updated_at = (
            latest_final_review_row.created_at.isoformat()
            if latest_final_review_row.created_at
            else None
        )
    final_review_summary_parts: List[str] = []
    if accepted_count > 0:
        final_review_summary_parts.append(f"已通过 {accepted_count} 条")
    if needs_more_evidence_count > 0:
        final_review_summary_parts.append(f"待补证据 {needs_more_evidence_count} 条")
    if redispatch_count > 0:
        final_review_summary_parts.append(f"已补派 {redispatch_count} 条")

    organizer_current_action = "结构化整理未开始"
    organizer_summary = "当前还没有可输出的问题。"
    organizer_accepted_issue_count = 0
    organizer_current_section: Optional[str] = None
    organizer_updated_at: Optional[str] = None
    if organizer_rows:
        latest_organizer_row, latest_organizer_meta = organizer_rows[-1]
        organizer_current_action = (
            _as_text(getattr(latest_organizer_row, "message", None))
            or "终审通过问题正在整理为最终输出"
        )
        organizer_updated_at = (
            latest_organizer_row.created_at.isoformat()
            if latest_organizer_row.created_at
            else None
        )
        organizer_current_section = _as_text(latest_organizer_meta.get("current_section")) or None
        if _as_text(getattr(latest_organizer_row, "event_kind", None)) == "result_summary":
            counts = latest_organizer_meta.get("counts")
            if isinstance(counts, dict):
                try:
                    organizer_accepted_issue_count = int(counts.get("total") or 0)
                except (TypeError, ValueError):
                    organizer_accepted_issue_count = 0
        else:
            try:
                organizer_accepted_issue_count = int(latest_organizer_meta.get("final_issues") or 0)
            except (TypeError, ValueError):
                organizer_accepted_issue_count = 0
        if organizer_accepted_issue_count > 0:
            organizer_summary = f"已整理 {organizer_accepted_issue_count} 条最终问题。"
        elif _as_text(latest_organizer_meta.get("task_stage")) == "organizer_converted":
            organizer_summary = "结构化整理已完成，等待问题汇总展示。"

    def _serialize_worker(item: Dict[str, object]) -> Dict[str, object]:
        return {
            "session_key": item.get("session_key"),
            "worker_name": item.get("worker_name"),
            "skill_id": item.get("skill_id"),
            "skill_label": item.get("skill_label"),
            "task_title": item.get("task_title"),
            "current_action": item.get("current_action"),
            "status": item.get("status"),
            "updated_at": item.get("updated_at"),
            "context": item.get("context") or {
                "source_sheet_no": None,
                "target_sheet_no": None,
                "sheet_no": None,
            },
            "recent_actions": item.get("recent_actions") or [],
        }

    return {
        "chief": {
            "title": "审图内核",
            "current_action": chief_current_action,
            "summary": "，".join(summary_parts) if summary_parts else "审图内核正在组织本轮复核调度。",
            "assigned_task_count": int(assigned_task_count or 0),
            "active_worker_count": active_count,
            "completed_worker_count": completed_count,
            "blocked_worker_count": blocked_count,
            "queued_task_count": queued_count,
            "issue_count": int(total_issues or 0),
            "updated_at": chief_updated_at,
        },
        "final_review": {
            "current_assignment_title": current_assignment_title,
            "current_action": final_review_current_action,
            "summary": "，".join(final_review_summary_parts) if final_review_summary_parts else "终审暂未产出决策。",
            "accepted_count": accepted_count,
            "needs_more_evidence_count": needs_more_evidence_count,
            "redispatch_count": redispatch_count,
            "updated_at": final_review_updated_at,
        },
        "organizer": {
            "current_action": organizer_current_action,
            "summary": organizer_summary,
            "accepted_issue_count": organizer_accepted_issue_count,
            "current_section": organizer_current_section,
            "updated_at": organizer_updated_at,
        },
        "worker_sessions": [_serialize_worker(item) for item in active_items],
        "recent_completed": [_serialize_worker(item) for item in completed_items],
    }


def get_audit_started_at_from_events(
    project_id: str,
    audit_version: Optional[int],
    db,
) -> Optional[str]:
    if audit_version is None:
        return None

    earliest_event = (
        db.query(AuditRunEvent)
        .filter(
            AuditRunEvent.project_id == project_id,
            AuditRunEvent.audit_version == audit_version,
        )
        .order_by(AuditRunEvent.created_at.asc(), AuditRunEvent.id.asc())
        .first()
    )
    if not earliest_event or not earliest_event.created_at:
        return None
    return earliest_event.created_at.isoformat()
