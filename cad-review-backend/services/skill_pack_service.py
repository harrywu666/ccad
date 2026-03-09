"""审查技能包服务。"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from sqlalchemy.orm import Session

from domain.sheet_normalization import normalize_index_no, normalize_sheet_no
from models import AuditSkillEntry, FeedbackSample


SKILL_TYPE_CATALOG: List[Dict[str, Any]] = [
    {
        "skill_type": "index",
        "label": "索引",
        "execution_mode": "code",
        "default_stage_keys": [],
        "allowed_stages": [],
    },
    {
        "skill_type": "dimension",
        "label": "尺寸",
        "execution_mode": "ai",
        "default_stage_keys": ["dimension_single_sheet", "dimension_pair_compare"],
        "allowed_stages": [
            {
                "stage_key": "dimension_single_sheet",
                "title": "尺寸单图语义分析",
                "description": "单张图的尺寸语义理解。",
            },
            {
                "stage_key": "dimension_pair_compare",
                "title": "尺寸双图对比",
                "description": "两张图之间的尺寸冲突比对。",
            },
        ],
    },
    {
        "skill_type": "material",
        "label": "材料",
        "execution_mode": "ai",
        "default_stage_keys": ["material_consistency_review"],
        "allowed_stages": [
            {
                "stage_key": "material_consistency_review",
                "title": "材料一致性审核",
                "description": "结合材料表和图中材料标注进行语义一致性审核。",
            },
        ],
    },
]

SKILL_TYPE_MAP = {item["skill_type"]: item for item in SKILL_TYPE_CATALOG}


def _loads_json_array(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(value, list):
        return []
    result: List[str] = []
    for item in value:
        text = str(item or "").strip()
        if text:
            result.append(text)
    return result


def _dumps_json_array(items: Optional[Iterable[str]]) -> Optional[str]:
    values = [str(item).strip() for item in (items or []) if str(item).strip()]
    if not values:
        return None
    return json.dumps(values, ensure_ascii=False)


def _default_stage_keys(skill_type: str) -> List[str]:
    definition = SKILL_TYPE_MAP.get(skill_type, {})
    return list(definition.get("default_stage_keys") or [])


def _validate_skill_type(skill_type: str) -> Dict[str, Any]:
    definition = SKILL_TYPE_MAP.get(skill_type)
    if not definition:
        raise ValueError(f"unknown_skill_type:{skill_type}")
    return definition


def _validate_stage_keys(skill_type: str, stage_keys: Optional[List[str]]) -> List[str]:
    definition = _validate_skill_type(skill_type)
    allowed = {item["stage_key"] for item in definition.get("allowed_stages") or []}
    normalized = [str(item).strip() for item in (stage_keys or []) if str(item).strip()]
    if not normalized:
        return _default_stage_keys(skill_type)
    invalid = [item for item in normalized if item not in allowed]
    if invalid:
        raise ValueError(f"invalid_stage_keys:{','.join(invalid)}")
    return normalized


def serialize_skill_entry(row: AuditSkillEntry) -> Dict[str, Any]:
    return {
        "id": row.id,
        "skill_type": row.skill_type,
        "title": row.title,
        "content": row.content,
        "source": row.source or "manual",
        "execution_mode": row.execution_mode,
        "stage_keys": _loads_json_array(row.stage_keys),
        "source_sample_ids": _loads_json_array(row.source_sample_ids),
        "is_active": bool(row.is_active),
        "priority": int(row.priority or 0),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_skill_types() -> Dict[str, List[Dict[str, Any]]]:
    return {"items": SKILL_TYPE_CATALOG}


def list_skill_entries(db: Session, skill_type: Optional[str] = None) -> Dict[str, List[Dict[str, Any]]]:
    query = db.query(AuditSkillEntry)
    if skill_type:
        _validate_skill_type(skill_type)
        query = query.filter(AuditSkillEntry.skill_type == skill_type)
    rows = query.order_by(
        AuditSkillEntry.skill_type.asc(),
        AuditSkillEntry.priority.asc(),
        AuditSkillEntry.created_at.asc(),
    ).all()
    return {"items": [serialize_skill_entry(row) for row in rows]}


def create_skill_entry(
    db: Session,
    *,
    skill_type: str,
    title: str,
    content: str,
    source: str = "manual",
    execution_mode: Optional[str] = None,
    stage_keys: Optional[List[str]] = None,
    source_sample_ids: Optional[List[str]] = None,
    is_active: bool = True,
    priority: int = 100,
) -> Dict[str, Any]:
    definition = _validate_skill_type(skill_type)
    normalized_title = str(title or "").strip()
    normalized_content = str(content or "").strip()
    if not normalized_title:
        raise ValueError("title_required")
    if not normalized_content:
        raise ValueError("content_required")

    resolved_execution_mode = execution_mode or str(definition["execution_mode"])
    resolved_stage_keys = _validate_stage_keys(skill_type, stage_keys)
    row = AuditSkillEntry(
        skill_type=skill_type,
        title=normalized_title,
        content=normalized_content,
        source=str(source or "manual").strip() or "manual",
        execution_mode=resolved_execution_mode,
        stage_keys=_dumps_json_array(resolved_stage_keys),
        source_sample_ids=_dumps_json_array(source_sample_ids),
        is_active=1 if is_active else 0,
        priority=int(priority),
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {"item": serialize_skill_entry(row)}


def update_skill_entry(
    db: Session,
    entry_id: str,
    *,
    title: Optional[str] = None,
    content: Optional[str] = None,
    stage_keys: Optional[List[str]] = None,
    priority: Optional[int] = None,
) -> Dict[str, Any]:
    row = db.query(AuditSkillEntry).filter(AuditSkillEntry.id == entry_id).first()
    if row is None:
        raise ValueError("skill_entry_not_found")

    if title is not None:
        normalized_title = str(title).strip()
        if not normalized_title:
            raise ValueError("title_required")
        row.title = normalized_title
    if content is not None:
        normalized_content = str(content).strip()
        if not normalized_content:
            raise ValueError("content_required")
        row.content = normalized_content
    if stage_keys is not None:
        row.stage_keys = _dumps_json_array(_validate_stage_keys(row.skill_type, stage_keys))
    if priority is not None:
        row.priority = int(priority)
    row.updated_at = datetime.now()
    db.commit()
    db.refresh(row)
    return {"item": serialize_skill_entry(row)}


def delete_skill_entry(db: Session, entry_id: str) -> Dict[str, bool]:
    row = db.query(AuditSkillEntry).filter(AuditSkillEntry.id == entry_id).first()
    if row is None:
        raise ValueError("skill_entry_not_found")
    db.delete(row)
    db.commit()
    return {"success": True}


def toggle_skill_entry(db: Session, entry_id: str, is_active: bool) -> Dict[str, Any]:
    row = db.query(AuditSkillEntry).filter(AuditSkillEntry.id == entry_id).first()
    if row is None:
        raise ValueError("skill_entry_not_found")
    row.is_active = 1 if is_active else 0
    row.updated_at = datetime.now()
    db.commit()
    db.refresh(row)
    return {"item": serialize_skill_entry(row)}


def _entry_applies_to_stage(row: AuditSkillEntry, stage_key: Optional[str]) -> bool:
    if not stage_key:
        return True
    execution_mode = str(row.execution_mode or "")
    if execution_mode != "ai":
        return True
    keys = _loads_json_array(row.stage_keys)
    if not keys:
        keys = _default_stage_keys(row.skill_type)
    if not keys:
        return True
    return stage_key in keys


def load_active_skill_rules(
    db: Session,
    *,
    skill_type: str,
    stage_key: Optional[str] = None,
) -> List[Dict[str, Any]]:
    _validate_skill_type(skill_type)
    rows = (
        db.query(AuditSkillEntry)
        .filter(
            AuditSkillEntry.skill_type == skill_type,
            AuditSkillEntry.is_active == 1,
        )
        .order_by(
            AuditSkillEntry.priority.asc(),
            AuditSkillEntry.created_at.asc(),
        )
        .all()
    )
    items = [
        serialize_skill_entry(row)
        for row in rows
        if _entry_applies_to_stage(row, stage_key)
    ]
    items.sort(key=lambda item: (0 if item["source"] == "manual" else 1, item["priority"]))
    return items


def format_skill_rules_block(rules: List[Dict[str, Any]]) -> str:
    if not rules:
        return ""
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for rule in rules:
        source = str(rule.get("source") or "manual")
        groups[source].append(rule)

    lines = ["---", "【审查知识库】以下规则在本次审核中同样生效：", ""]
    manual_rules = groups.get("manual", [])
    if manual_rules:
        lines.append("■ 基础审查规则")
        for idx, rule in enumerate(manual_rules, start=1):
            lines.append(f"{idx}. {rule['title']}：{rule['content']}")
        lines.append("")
    auto_rules = groups.get("auto", [])
    if auto_rules:
        lines.append("■ 历史经验修正")
        for idx, rule in enumerate(auto_rules, start=1):
            lines.append(f"{idx}. {rule['title']}：{rule['content']}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _deep_merge_dict(target: Dict[str, Any], source: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in source.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            _deep_merge_dict(target[key], value)
        else:
            target[key] = value
    return target


def _parse_runtime_rule_payload(content: Optional[str]) -> Dict[str, Any]:
    text = str(content or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def load_runtime_skill_profile(
    db: Session,
    *,
    skill_type: str,
    stage_key: Optional[str] = None,
) -> Dict[str, Any]:
    rules = load_active_skill_rules(db, skill_type=skill_type, stage_key=stage_key)
    profile: Dict[str, Any] = {
        "skill_type": skill_type,
        "task_bias": {},
        "evidence_bias": {},
        "judgement_policy": {},
        "prompt_rules": rules,
    }
    for rule in rules:
        payload = _parse_runtime_rule_payload(rule.get("content"))
        for key in ("task_bias", "evidence_bias", "judgement_policy"):
            value = payload.get(key)
            if isinstance(value, dict):
                _deep_merge_dict(profile[key], value)
    return profile


def build_index_alias_map(rules: List[Dict[str, Any]]) -> Dict[str, str]:
    groups: List[List[str]] = []
    for rule in rules:
        text = " ".join(
            [
                str(rule.get("title") or "").strip(),
                str(rule.get("content") or "").strip(),
            ]
        ).strip()
        if not text:
            continue
        if "=" in text:
            parts = re.split(r"[=＝]+", text, maxsplit=1)
            tokens = re.findall(r"[A-Za-z][A-Za-z0-9.\-_]*", " ".join(parts[:2]))
        elif any(flag in text for flag in ("同一图号", "视为同一", "等同")):
            tokens = re.findall(r"[A-Za-z][A-Za-z0-9.\-_]*", text)
        else:
            tokens = []
        normalized = []
        for token in tokens[:2]:
            key = normalize_sheet_no(token) or normalize_index_no(token)
            if key:
                normalized.append(key)
        if len(normalized) >= 2:
            groups.append(normalized[:2])

    alias_map: Dict[str, str] = {}
    for group in groups:
        canonical = sorted(group)[0]
        for item in group:
            alias_map[item] = canonical
    return alias_map


def canonicalize_index_key(value: Optional[str], alias_map: Dict[str, str]) -> str:
    key = normalize_index_no(value)
    if not key:
        return ""
    return alias_map.get(key, key)


def canonicalize_sheet_key(value: Optional[str], alias_map: Dict[str, str]) -> str:
    key = normalize_sheet_no(value)
    if not key:
        return ""
    return alias_map.get(key, key)


def generate_rules(db: Session, skill_type: str) -> Dict[str, Any]:
    definition = _validate_skill_type(skill_type)
    samples = (
        db.query(FeedbackSample)
        .filter(
            FeedbackSample.issue_type == skill_type,
            FeedbackSample.curation_status == "accepted",
        )
        .order_by(FeedbackSample.curated_at.desc(), FeedbackSample.created_at.desc())
        .limit(20)
        .all()
    )
    if not samples:
        return {"items": [], "generated": 0}

    unique_notes: List[str] = []
    sample_ids: List[str] = []
    for sample in samples:
        sample_ids.append(sample.id)
        for candidate in (sample.user_note, sample.description):
            text = str(candidate or "").strip()
            if text and text not in unique_notes:
                unique_notes.append(text)
    if not unique_notes:
        unique_notes.append(f"结合已采纳{definition['label']}误报样本，复核相似表达与上下文。")

    content = "；".join(unique_notes[:3])
    created = create_skill_entry(
        db,
        skill_type=skill_type,
        title=f"{definition['label']}调优草稿",
        content=content,
        source="auto",
        execution_mode=definition["execution_mode"],
        stage_keys=_default_stage_keys(skill_type),
        source_sample_ids=sample_ids,
        is_active=False,
        priority=50,
    )
    return {"items": [created["item"]], "generated": 1}
