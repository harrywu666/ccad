"""证据规划器。"""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Dict, List, Optional

from services.audit_runtime.contracts import EvidencePackType, EvidencePlanItem
from services.audit_runtime.visual_budget import get_active_visual_budget


def build_default_evidence_policy() -> Dict[str, Dict[str, Any]]:
    return {
        "index": {
            "default_pack_type": EvidencePackType.OVERVIEW_PACK.value,
            "strategy": "索引问题默认先看来源图总览，仅在涉及目标图时补双图总览复核",
        },
        "relationship": {
            "default_pack_type": EvidencePackType.PAIRED_OVERVIEW_PACK.value,
            "strategy": "先用双图总览确认是否存在跨图关系，再决定是否升级证据深度",
        },
        "dimension": {
            "default_pack_type": EvidencePackType.OVERVIEW_PACK.value,
            "strategy": "优先依赖结构化数据，仅在需要视觉复核时申请概览或聚焦证据",
        },
        "material": {
            "default_pack_type": EvidencePackType.FOCUS_PACK.value,
            "strategy": "默认先看材料表与重点区域，不直接申请深度证据包",
        },
    }


def plan_evidence_requests(
    *,
    task_type: str,
    source_sheet_no: str,
    target_sheet_no: Optional[str] = None,
    requires_visual: bool = True,
    round_index: int = 1,
    reason: Optional[str] = None,
    skill_profile: Optional[Dict[str, Any]] = None,
    feedback_profile: Optional[Dict[str, Any]] = None,
    priority: str = "normal",
) -> List[EvidencePlanItem]:
    task_key = str(task_type or "").strip().lower()
    preferred_pack_type = _resolve_preferred_pack_type(task_key, skill_profile, feedback_profile)

    if task_key == "relationship":
        plans = [
            EvidencePlanItem(
                task_type="relationship",
                pack_type=preferred_pack_type or EvidencePackType.PAIRED_OVERVIEW_PACK,
                source_sheet_no=source_sheet_no,
                target_sheet_no=target_sheet_no,
                round_index=round_index,
                reason=reason or "先用双图总览判断是否值得继续展开关系复核",
                requires_visual=True,
            )
        ]
        return _apply_budget(plans, priority=priority)

    if task_key == "index":
        default_pack = preferred_pack_type
        if default_pack is None:
            default_pack = (
                EvidencePackType.PAIRED_OVERVIEW_PACK
                if target_sheet_no
                else EvidencePackType.OVERVIEW_PACK
            )
        plans = [
            EvidencePlanItem(
                task_type="index",
                pack_type=default_pack,
                source_sheet_no=source_sheet_no,
                target_sheet_no=target_sheet_no,
                round_index=round_index,
                reason=reason or "索引规则结果存在歧义，先申请总览证据做视觉复核",
                requires_visual=requires_visual,
            )
        ]
        return _apply_budget(plans, priority=priority)

    if task_key == "dimension":
        if not requires_visual:
            return []
        default_pack = preferred_pack_type
        if default_pack is None:
            default_pack = (
                EvidencePackType.PAIRED_OVERVIEW_PACK
                if target_sheet_no
                else EvidencePackType.OVERVIEW_PACK
            )
        plans = [
            EvidencePlanItem(
                task_type="dimension",
                pack_type=default_pack,
                source_sheet_no=source_sheet_no,
                target_sheet_no=target_sheet_no,
                round_index=round_index,
                reason=reason or "当前尺寸任务需要视觉复核，先申请概览证据",
                requires_visual=True,
            )
        ]
        return _apply_budget(plans, priority=priority)

    if task_key == "material":
        plans = [
            EvidencePlanItem(
                task_type="material",
                pack_type=preferred_pack_type or EvidencePackType.FOCUS_PACK,
                source_sheet_no=source_sheet_no,
                target_sheet_no=target_sheet_no,
                round_index=round_index,
                reason=reason or "默认先核对材料表和重点区域，不直接进入深度证据",
                requires_visual=requires_visual,
            )
        ]
        return _apply_budget(plans, priority=priority)

    plans = [
        EvidencePlanItem(
            task_type=task_key or "unknown",
            pack_type=preferred_pack_type or EvidencePackType.OVERVIEW_PACK,
            source_sheet_no=source_sheet_no,
            target_sheet_no=target_sheet_no,
            round_index=round_index,
            reason=reason or "未命中特定策略，退回概览证据",
            requires_visual=requires_visual,
        )
    ]
    return _apply_budget(plans, priority=priority)


def plan_lite(
    *,
    task_type: str,
    source_sheet_no: str,
    target_sheet_no: Optional[str] = None,
    requires_visual: bool = True,
    reason: Optional[str] = None,
    skill_profile: Optional[Dict[str, Any]] = None,
    feedback_profile: Optional[Dict[str, Any]] = None,
    priority: str = "normal",
) -> List[EvidencePlanItem]:
    """首轮轻量证据规划入口。"""
    return plan_evidence_requests(
        task_type=task_type,
        source_sheet_no=source_sheet_no,
        target_sheet_no=target_sheet_no,
        requires_visual=requires_visual,
        round_index=1,
        reason=reason,
        skill_profile=skill_profile,
        feedback_profile=feedback_profile,
        priority=priority,
    )


def next_pack_type(pack_type: EvidencePackType) -> EvidencePackType:
    if pack_type == EvidencePackType.OVERVIEW_PACK:
        return EvidencePackType.FOCUS_PACK
    if pack_type == EvidencePackType.PAIRED_OVERVIEW_PACK:
        return EvidencePackType.FOCUS_PACK
    return EvidencePackType.DEEP_PACK


def plan_deep(
    *,
    task_type: str,
    source_sheet_no: str,
    target_sheet_no: Optional[str] = None,
    current_pack_type: EvidencePackType,
    current_round: int,
    triggered_by: str,
    skill_profile: Optional[Dict[str, Any]] = None,
    feedback_profile: Optional[Dict[str, Any]] = None,
    priority: str = "normal",
) -> List[EvidencePlanItem]:
    """按需补图入口。最多只允许第二轮真正补图。"""
    if current_round >= 2:
        return []

    plans = [
        EvidencePlanItem(
            task_type=str(task_type or "").strip().lower() or "unknown",
            pack_type=next_pack_type(current_pack_type),
            source_sheet_no=source_sheet_no,
            target_sheet_no=target_sheet_no,
            round_index=current_round + 1,
            reason=f"由于 {triggered_by}，补一轮更深证据",
            requires_visual=True,
            meta={
                "triggered_by": triggered_by,
                "progressive": True,
                "skill_profile_used": bool(skill_profile),
                "feedback_profile_used": bool(feedback_profile),
            },
        )
    ]
    return _apply_budget(plans, priority=priority)


def _resolve_preferred_pack_type(
    task_type: str,
    skill_profile: Optional[Dict[str, Any]],
    feedback_profile: Optional[Dict[str, Any]],
) -> Optional[EvidencePackType]:
    evidence_bias = (skill_profile or {}).get("evidence_bias") or {}
    task_bias = evidence_bias.get(task_type) if isinstance(evidence_bias.get(task_type), dict) else evidence_bias
    preferred = str((task_bias or {}).get("preferred_pack_type") or "").strip()
    if preferred:
        try:
            return EvidencePackType(preferred)
        except ValueError:
            pass

    hint = (feedback_profile or {}).get("experience_hint")
    if isinstance(hint, dict):
        if str(hint.get("intervention_level") or "").strip().lower() in {"soft", "hard"}:
            if task_type in {"relationship", "dimension", "material"}:
                return EvidencePackType.FOCUS_PACK

    if bool((feedback_profile or {}).get("needs_secondary_review")):
        if task_type == "relationship":
            return EvidencePackType.FOCUS_PACK
        if task_type == "dimension":
            return EvidencePackType.FOCUS_PACK
        if task_type == "material":
            return EvidencePackType.FOCUS_PACK
    return None


def _apply_budget(
    plans: List[EvidencePlanItem],
    *,
    priority: str,
) -> List[EvidencePlanItem]:
    budget = get_active_visual_budget()
    if budget is None:
        return plans

    adjusted: List[EvidencePlanItem] = []
    for item in plans:
        before = budget.snapshot()
        chosen = budget.request_pack(item.pack_type, priority=priority)
        if chosen is None:
            chosen = EvidencePackType.OVERVIEW_PACK
        after = budget.snapshot()
        meta = dict(item.meta or {})
        meta.update(
            {
                "requested_pack_type": item.pack_type.value,
                "final_pack_type": chosen.value,
                "budget_priority": priority,
                "budget_before": before,
                "budget_after": after,
            }
        )
        adjusted.append(replace(item, pack_type=chosen, meta=meta))
    return adjusted
