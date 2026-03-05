"""
审核任务规划服务
将 sheet_contexts + sheet_edges 转换为可执行的 audit_tasks。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from models import AuditTask, SheetContext, SheetEdge


def _norm_sheet_no(value: Optional[str]) -> str:
    if not value:
        return ""
    s = str(value).strip().upper()
    s = re.sub(r"[\s\-_./\\()（）【】\[\]{}:：|]+", "", s)
    return s


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
        evidence = json.loads(edge.evidence_json or "{}")
        return int(evidence.get("mention_count") or 0)
    except Exception:
        return 0


def build_audit_tasks(project_id: str, audit_version: int, db) -> Dict[str, Any]:
    """
    基于上下文和图纸关系边构建审核任务。

    Returns:
        {
          "total": int,
          "index_tasks": int,
          "dimension_tasks": int,
          "material_tasks": int
        }
    """
    # 幂等：同版本重建任务
    db.query(AuditTask).filter(
        AuditTask.project_id == project_id,
        AuditTask.audit_version == audit_version,
    ).delete(synchronize_session=False)

    contexts = (
        db.query(SheetContext)
        .filter(
            SheetContext.project_id == project_id,
            SheetContext.status == "ready",
        )
        .all()
    )
    edges = (
        db.query(SheetEdge)
        .filter(SheetEdge.project_id == project_id)
        .all()
    )

    context_by_key: Dict[str, SheetContext] = {}
    for ctx in contexts:
        key = _norm_sheet_no(ctx.sheet_no)
        if key:
            context_by_key[key] = ctx

    tasks: List[AuditTask] = []
    dedupe_keys = set()

    index_tasks = 0
    dimension_tasks = 0
    material_tasks = 0

    # 1) 索引核对任务：每张 ready 图至少可有一个 index_check 任务（有索引才创建）
    for ctx in contexts:
        meta = _load_meta(ctx.meta_json)
        stats = meta.get("stats") or {}
        index_count = int(stats.get("indexes") or 0)
        if index_count <= 0:
            continue

        sheet_no = (ctx.sheet_no or "").strip()
        if not sheet_no:
            continue

        dedupe = ("index", sheet_no, "")
        if dedupe in dedupe_keys:
            continue
        dedupe_keys.add(dedupe)

        is_plan = _is_plan_sheet(sheet_no, ctx.sheet_name or "")
        priority = 1 if is_plan else 2
        task = AuditTask(
            project_id=project_id,
            audit_version=audit_version,
            task_type="index",
            source_sheet_no=sheet_no,
            target_sheet_no=None,
            priority=priority,
            status="pending",
            trace_json=json.dumps(
                {
                    "planner": "task_planner_v1",
                    "reason": "sheet_has_indexes",
                    "index_count": index_count,
                    "is_plan_sheet": is_plan,
                },
                ensure_ascii=False,
            ),
        )
        tasks.append(task)
        index_tasks += 1

    # 2) 尺寸/材料任务：按索引边构建平面->目标图任务
    for edge in edges:
        src_no = (edge.source_sheet_no or "").strip()
        tgt_no = (edge.target_sheet_no or "").strip()
        if not src_no or not tgt_no:
            continue

        src_ctx = context_by_key.get(_norm_sheet_no(src_no))
        tgt_ctx = context_by_key.get(_norm_sheet_no(tgt_no))
        if not src_ctx or not tgt_ctx:
            continue

        is_plan = _is_plan_sheet(src_no, src_ctx.sheet_name or "")
        mention_count = _edge_mention_count(edge)

        pair_specs: List[Tuple[str, int, str]] = [
            ("dimension", 1 if is_plan else 3, "index_pair_dimension_check"),
            ("material", 2 if is_plan else 4, "index_pair_material_check"),
        ]

        for task_type, priority, reason in pair_specs:
            dedupe = (task_type, src_no, tgt_no)
            if dedupe in dedupe_keys:
                continue
            dedupe_keys.add(dedupe)

            task = AuditTask(
                project_id=project_id,
                audit_version=audit_version,
                task_type=task_type,
                source_sheet_no=src_no,
                target_sheet_no=tgt_no,
                priority=priority,
                status="pending",
                trace_json=json.dumps(
                    {
                        "planner": "task_planner_v1",
                        "reason": reason,
                        "edge_type": edge.edge_type,
                        "edge_confidence": edge.confidence,
                        "edge_mentions": mention_count,
                        "is_plan_sheet": is_plan,
                    },
                    ensure_ascii=False,
                ),
            )
            tasks.append(task)
            if task_type == "dimension":
                dimension_tasks += 1
            elif task_type == "material":
                material_tasks += 1

    if tasks:
        db.add_all(tasks)
    db.commit()

    return {
        "total": len(tasks),
        "index_tasks": index_tasks,
        "dimension_tasks": dimension_tasks,
        "material_tasks": material_tasks,
    }

