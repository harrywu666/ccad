"""
总控 LLM 任务编排服务
为审核任务图（DAG）生成提供“LLM优先 + 严格校验 + 回退”能力。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import threading
from typing import Any, Dict, List, Optional, Tuple

from models import SheetContext, SheetEdge
from services.kimi_service import call_kimi

logger = logging.getLogger(__name__)

ALLOWED_TASK_TYPES = {"index", "dimension", "material"}


def _env_bool(name: str, default: bool = True) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _norm_sheet_no(value: Optional[str]) -> str:
    if not value:
        return ""
    s = str(value).strip().upper()
    s = re.sub(r"[\s\-_./\\()（）【】\[\]{}:：|]+", "", s)
    return s


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _is_plan_sheet(sheet_no: str, sheet_name: str) -> bool:
    no = (sheet_no or "").upper()
    name = (sheet_name or "").upper()
    name_cn = sheet_name or ""

    no_hint = no.startswith("A1")
    cn_hint = ("平面" in name_cn) or ("索引" in name_cn)
    en_hint = ("PLAN" in name) or ("FURNITURE" in name) or ("LAYOUT" in name)
    exclude_hint = ("ELEVATION" in name) or ("SECTION" in name) or ("NODE" in name) or ("DETAIL" in name)
    return bool((no_hint or cn_hint or en_hint) and not exclude_hint)


def _load_meta(meta_json: Optional[str]) -> Dict[str, Any]:
    if not meta_json:
        return {}
    try:
        obj = json.loads(meta_json)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}


def _edge_mention_count(edge: SheetEdge) -> int:
    try:
        payload = json.loads(edge.evidence_json or "{}")
        return _safe_int(payload.get("mention_count"), 0)
    except Exception:
        return 0


def _run_async(coro):  # noqa: ANN001
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    if not loop.is_running():
        return loop.run_until_complete(coro)

    holder: Dict[str, Any] = {}

    def _runner() -> None:
        try:
            holder["result"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            holder["error"] = exc

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()
    if "error" in holder:
        raise holder["error"]
    return holder.get("result")


def _resolve_master_planner_prompts(payload: Dict[str, Any]) -> Dict[str, str]:
    """通过 ai_prompt_service 解析 master_task_planner 提示词。"""
    from services.ai_prompt_service import resolve_stage_prompts

    return resolve_stage_prompts(
        "master_task_planner",
        {"payload_json": json.dumps(payload, ensure_ascii=False)},
    )


def _default_priority(task_type: str, is_plan_sheet: bool) -> int:
    if task_type == "index":
        return 1 if is_plan_sheet else 2
    if task_type == "dimension":
        return 1 if is_plan_sheet else 3
    if task_type == "material":
        return 2 if is_plan_sheet else 4
    return 5


def _normalize_task_item(
    item: Dict[str, Any],
    *,
    context_meta: Dict[str, Dict[str, Any]],
    allowed_edges: set[Tuple[str, str]],
) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    task_type = str(
        item.get("task_type")
        or item.get("type")
        or item.get("task")
        or ""
    ).strip().lower()
    if task_type not in ALLOWED_TASK_TYPES:
        return None, f"unsupported_task_type:{task_type}"

    src_raw = str(item.get("source_sheet_no") or item.get("source") or "").strip()
    src_key = _norm_sheet_no(src_raw)
    if not src_key or src_key not in context_meta:
        return None, f"invalid_source:{src_raw}"
    source_sheet_no = context_meta[src_key]["sheet_no"]
    source_is_plan = bool(context_meta[src_key].get("is_plan_sheet"))
    source_index_count = _safe_int(context_meta[src_key].get("index_count"), 0)

    target_sheet_no: Optional[str] = None
    tgt_key = ""
    if task_type in {"dimension", "material"}:
        tgt_raw = str(item.get("target_sheet_no") or item.get("target") or "").strip()
        tgt_key = _norm_sheet_no(tgt_raw)
        if not tgt_key or tgt_key not in context_meta:
            return None, f"invalid_target:{tgt_raw}"
        if tgt_key == src_key:
            return None, f"same_sheet_pair:{source_sheet_no}"
        if (src_key, tgt_key) not in allowed_edges:
            return None, f"edge_not_allowed:{source_sheet_no}->{context_meta[tgt_key]['sheet_no']}"
        target_sheet_no = context_meta[tgt_key]["sheet_no"]
    elif source_index_count <= 0:
        return None, f"index_task_without_indexes:{source_sheet_no}"

    priority_raw = item.get("priority")
    try:
        priority = int(priority_raw)
    except (TypeError, ValueError):
        priority = _default_priority(task_type, source_is_plan)
    priority = max(1, min(5, priority))

    reason = str(item.get("reason") or item.get("why") or "").strip()
    evidence = item.get("evidence")

    return (
        {
            "task_type": task_type,
            "source_sheet_no": source_sheet_no,
            "target_sheet_no": target_sheet_no,
            "priority": priority,
            "reason": reason,
            "evidence": evidence if isinstance(evidence, (dict, list, str, int, float, bool)) else None,
        },
        None,
    )


def _extract_tasks(result: Any) -> List[Dict[str, Any]]:
    if isinstance(result, dict):
        tasks = result.get("tasks")
        if isinstance(tasks, list):
            return [item for item in tasks if isinstance(item, dict)]
    if isinstance(result, list):
        return [item for item in result if isinstance(item, dict)]
    return []


def plan_with_master_llm(
    project_id: str,
    contexts: List[SheetContext],
    edges: List[SheetEdge],
) -> Dict[str, Any]:
    """
    使用总控 LLM 规划任务。

    Returns:
      {
        "ok": bool,
        "tasks": [...],   # 规范化后的任务
        "planner": "master_llm_v1",
        "reason": "...",  # ok=False 时给出原因
        "warnings": [...],
      }
    """
    if not _env_bool("AUDIT_MASTER_PLANNER_ENABLED", True):
        return {"ok": False, "reason": "disabled"}

    ready_contexts = [
        ctx for ctx in contexts
        if ctx.status == "ready" and str(ctx.sheet_no or "").strip()
    ]
    if not ready_contexts:
        return {"ok": False, "reason": "no_ready_contexts"}
    if not edges:
        return {"ok": False, "reason": "no_edges"}

    context_meta: Dict[str, Dict[str, Any]] = {}
    context_items: List[Dict[str, Any]] = []
    for ctx in ready_contexts:
        sheet_no = str(ctx.sheet_no or "").strip()
        sheet_name = str(ctx.sheet_name or "").strip()
        key = _norm_sheet_no(sheet_no)
        if not key:
            continue
        meta = _load_meta(ctx.meta_json)
        stats = meta.get("stats") if isinstance(meta.get("stats"), dict) else {}
        index_count = _safe_int(stats.get("indexes"), 0)
        is_plan = _is_plan_sheet(sheet_no, sheet_name)
        context_meta[key] = {
            "sheet_no": sheet_no,
            "sheet_name": sheet_name,
            "index_count": index_count,
            "is_plan_sheet": is_plan,
        }
        context_items.append(
            {
                "sheet_no": sheet_no,
                "sheet_name": sheet_name,
                "index_count": index_count,
                "is_plan_sheet": is_plan,
            }
        )

    edge_items: List[Dict[str, Any]] = []
    allowed_edges: set[Tuple[str, str]] = set()
    for edge in edges:
        src_raw = str(edge.source_sheet_no or "").strip()
        tgt_raw = str(edge.target_sheet_no or "").strip()
        src_key = _norm_sheet_no(src_raw)
        tgt_key = _norm_sheet_no(tgt_raw)
        if not src_key or not tgt_key or src_key == tgt_key:
            continue
        if src_key not in context_meta or tgt_key not in context_meta:
            continue
        allowed_edges.add((src_key, tgt_key))
        edge_items.append(
            {
                "source_sheet_no": context_meta[src_key]["sheet_no"],
                "target_sheet_no": context_meta[tgt_key]["sheet_no"],
                "edge_type": edge.edge_type or "index_ref",
                "confidence": edge.confidence,
                "edge_mention_count": _edge_mention_count(edge),
            }
        )

    if not allowed_edges:
        return {"ok": False, "reason": "no_valid_edges"}

    payload = {
        "project_id": project_id,
        "contexts": context_items,
        "edges": edge_items,
    }

    try:
        prompts = _resolve_master_planner_prompts(payload)
        result = _run_async(
            call_kimi(
                system_prompt=prompts["system_prompt"],
                user_prompt=prompts["user_prompt"],
                temperature=0.0,
            )
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("master_planner failed project=%s error=%s", project_id, exc)
        return {"ok": False, "reason": f"llm_error:{exc}"}

    raw_tasks = _extract_tasks(result)
    if not raw_tasks:
        logger.warning("master_planner empty result project=%s type=%s", project_id, type(result).__name__)
        return {"ok": False, "reason": "empty_or_invalid_output"}

    normalized: List[Dict[str, Any]] = []
    dedupe: set[Tuple[str, str, str]] = set()
    warnings: List[str] = []
    for item in raw_tasks:
        task, err = _normalize_task_item(
            item,
            context_meta=context_meta,
            allowed_edges=allowed_edges,
        )
        if not task:
            if err:
                warnings.append(err)
            continue

        dedupe_key = (
            task["task_type"],
            _norm_sheet_no(task["source_sheet_no"]),
            _norm_sheet_no(task["target_sheet_no"] or ""),
        )
        if dedupe_key in dedupe:
            continue
        dedupe.add(dedupe_key)
        normalized.append(task)

    if not normalized:
        logger.warning(
            "master_planner all tasks rejected project=%s warnings=%s",
            project_id,
            warnings[:8],
        )
        return {"ok": False, "reason": "all_tasks_rejected", "warnings": warnings[:30]}

    # 覆盖性校验：防止LLM漏任务导致审核链路断档
    normalized_keys = {
        (
            str(task.get("task_type") or ""),
            _norm_sheet_no(str(task.get("source_sheet_no") or "")),
            _norm_sheet_no(str(task.get("target_sheet_no") or "")),
        )
        for task in normalized
    }

    missing_required: List[str] = []
    for src_key, meta in context_meta.items():
        if _safe_int(meta.get("index_count"), 0) > 0 and ("index", src_key, "") not in normalized_keys:
            missing_required.append(f"missing:index:{meta.get('sheet_no')}")
    for src_key, tgt_key in allowed_edges:
        src_no = context_meta[src_key]["sheet_no"]
        tgt_no = context_meta[tgt_key]["sheet_no"]
        if ("dimension", src_key, tgt_key) not in normalized_keys:
            missing_required.append(f"missing:dimension:{src_no}->{tgt_no}")
        if ("material", src_key, tgt_key) not in normalized_keys:
            missing_required.append(f"missing:material:{src_no}->{tgt_no}")

    if missing_required:
        logger.warning(
            "master_planner coverage incomplete project=%s missing=%s",
            project_id,
            missing_required[:12],
        )
        return {
            "ok": False,
            "reason": "coverage_incomplete",
            "warnings": (warnings + missing_required)[:30],
        }

    logger.info(
        "master_planner success project=%s tasks=%s warnings=%s",
        project_id,
        len(normalized),
        len(warnings),
    )
    return {
        "ok": True,
        "planner": "master_llm_v1",
        "tasks": normalized,
        "warnings": warnings[:30],
        "raw_type": type(result).__name__,
    }
