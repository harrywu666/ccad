"""证据规划器。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from services.audit_runtime.contracts import EvidencePackType, EvidencePlanItem


def build_default_evidence_policy() -> Dict[str, Dict[str, Any]]:
    return {
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
) -> List[EvidencePlanItem]:
    task_key = str(task_type or "").strip().lower()
    preferred_pack_type = _resolve_preferred_pack_type(task_key, skill_profile, feedback_profile)

    if task_key == "relationship":
        return [
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
        return [
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

    if task_key == "material":
        return [
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

    return [
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

    if bool((feedback_profile or {}).get("needs_secondary_review")):
        if task_type == "relationship":
            return EvidencePackType.FOCUS_PACK
        if task_type == "dimension":
            return EvidencePackType.FOCUS_PACK
        if task_type == "material":
            return EvidencePackType.FOCUS_PACK
    return None
