"""Material audit implementation."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional

from domain.sheet_normalization import normalize_sheet_no
from domain.text_cleaning import strip_mtext_formatting
from models import AuditResult, JsonData
from services.ai_prompt_service import resolve_stage_system_prompt_with_skills
from services.audit.common import build_anchor, to_evidence_json
from services.audit.prompt_builder import build_material_review_prompt, compact_material_rows
from services.coordinate_service import enrich_json_with_coordinates
from services.kimi_service import call_kimi

logger = logging.getLogger(__name__)


async def _run_material_ai_review(
    *,
    sheet_no: str,
    material_table: List[Dict[str, Any]],
    material_used: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    result = await call_kimi(
        system_prompt=resolve_stage_system_prompt_with_skills(
            "material_consistency_review",
            "material",
        ),
        user_prompt=build_material_review_prompt(
            sheet_no,
            compact_material_rows(material_table),
            compact_material_rows(material_used),
        ),
        temperature=0.0,
    )
    if not isinstance(result, list):
        return []
    return [item for item in result if isinstance(item, dict)]


# 功能说明：执行材料审核主函数，检查材料表中材料定义和使用的一致性
def audit_materials(
    project_id: str,
    audit_version: int,
    db,
    sheet_filters: Optional[List[str]] = None,
) -> List[AuditResult]:
    allowed_sheet_keys: Optional[set[str]] = None
    if sheet_filters:
        allowed_sheet_keys = {
            normalize_sheet_no(item) for item in sheet_filters if normalize_sheet_no(item)
        }
        if not allowed_sheet_keys:
            return []

    json_list = (
        db.query(JsonData)
        .filter(
            JsonData.project_id == project_id,
            JsonData.is_latest == 1,
        )
        .all()
    )

    issues: List[AuditResult] = []
    seen_keys: set[tuple[str, str, str]] = set()

    # 功能说明：标准化材料编号（去除空格和特殊字符，转大写）
    def norm_code(value: Optional[str]) -> str:
        if not value:
            return ""
        text = str(value).strip().upper()
        text = re.sub(r"[\s\-_./\\()（）【】\[\]{}:：|]+", "", text)
        return text

    # 功能说明：标准化材料名称（去除多余空格）
    def norm_name(value: Optional[str]) -> str:
        if not value:
            return ""
        text = str(value).strip()
        text = re.sub(r"\s+", "", text)
        return text

    # 功能说明：验证材料编号格式是否有效（包含字母和数字，长度不超过12）
    def is_valid_material_code(code_key: str) -> bool:
        if not code_key:
            return False
        if len(code_key) > 12:
            return False
        if not any(ch.isalpha() for ch in code_key):
            return False
        if not any(ch.isdigit() for ch in code_key):
            return False
        return re.match(r"^[A-Z]*\d+[A-Z0-9]*$", code_key) is not None

    def append_issue(issue: AuditResult) -> None:
        key = (
            str(issue.sheet_no_a or "").strip(),
            str(issue.location or "").strip(),
            str(issue.description or "").strip(),
        )
        if key in seen_keys:
            return
        seen_keys.add(key)
        db.add(issue)
        issues.append(issue)

    for json_data in json_list:
        if allowed_sheet_keys is not None:
            current_key = normalize_sheet_no(json_data.sheet_no)
            if not current_key or current_key not in allowed_sheet_keys:
                continue
        if not json_data.json_path:
            continue

        try:
            with open(json_data.json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue

        data = enrich_json_with_coordinates(data)

        raw_table = data.get("material_table", []) or []
        raw_used = data.get("materials", []) or []

        material_anchor_by_code: Dict[str, Dict[str, Any]] = {}
        for mat in raw_used:
            code_raw = str(mat.get("code", "") or "").strip()
            code_key = norm_code(code_raw)
            if not is_valid_material_code(code_key):
                continue
            if code_key in material_anchor_by_code:
                continue
            anchor = build_anchor(
                role="single",
                sheet_no=json_data.sheet_no,
                grid=str(mat.get("grid") or "").strip(),
                global_pct=mat.get("global_pct") if isinstance(mat.get("global_pct"), dict) else None,
                confidence=1.0,
                origin="material",
            )
            if anchor:
                material_anchor_by_code[code_key] = anchor

        table_map: Dict[str, Dict[str, str]] = {}
        for item in raw_table:
            code_raw = str(item.get("code", "") or "").strip()
            name_raw = strip_mtext_formatting(str(item.get("name", "") or ""))
            code_key = norm_code(code_raw)
            if not is_valid_material_code(code_key):
                continue
            if code_key not in table_map:
                table_map[code_key] = {"code": code_raw, "name": name_raw}

        used_map: Dict[str, Dict[str, str]] = {}
        for item in raw_used:
            code_raw = str(item.get("code", "") or "").strip()
            name_raw = strip_mtext_formatting(str(item.get("name", "") or ""))
            code_key = norm_code(code_raw)
            if not is_valid_material_code(code_key):
                continue
            if code_key not in used_map:
                used_map[code_key] = {"code": code_raw, "name": name_raw}

        for code_key, used_item in used_map.items():
            if code_key in table_map:
                continue
            anchor = material_anchor_by_code.get(code_key)
            issue = AuditResult(
                project_id=project_id,
                audit_version=audit_version,
                type="material",
                severity="error",
                sheet_no_a=json_data.sheet_no,
                location=f"材料标注{used_item['code']}",
                description=(
                    f"图纸{json_data.sheet_no}中使用了材料编号{used_item['code']}（{used_item['name'] or '未命名'}），"
                    "但材料表中未找到定义。"
                ),
                evidence_json=to_evidence_json(
                    [anchor] if anchor else [],
                    unlocated_reason=None if anchor else "material_used_without_location",
                ),
            )
            append_issue(issue)

        for code_key, table_item in table_map.items():
            if code_key in used_map:
                continue
            issue = AuditResult(
                project_id=project_id,
                audit_version=audit_version,
                type="material",
                severity="info",
                sheet_no_a=json_data.sheet_no,
                location=f"材料表{table_item['code']}",
                description=(
                    f"材料表中定义了材料编号{table_item['code']}（{table_item['name'] or '未命名'}），"
                    "但在图纸标注中未使用。"
                ),
                evidence_json=to_evidence_json([], unlocated_reason="material_table_only_no_anchor"),
            )
            append_issue(issue)

        for code_key, used_item in used_map.items():
            table_item = table_map.get(code_key)
            if not table_item:
                continue
            used_name = norm_name(used_item.get("name"))
            table_name = norm_name(table_item.get("name"))
            if not used_name or not table_name:
                continue
            if used_name == table_name:
                continue
            similarity = SequenceMatcher(None, used_name, table_name).ratio()
            if similarity >= 0.92:
                continue
            anchor = material_anchor_by_code.get(code_key)
            issue = AuditResult(
                project_id=project_id,
                audit_version=audit_version,
                type="material",
                severity="warning",
                sheet_no_a=json_data.sheet_no,
                location=f"材料编号{used_item['code']}",
                description=(
                    f"图纸中材料编号{used_item['code']}名称为「{used_item['name'] or '未命名'}」，"
                    f"材料表中同编号名称为「{table_item['name'] or '未命名'}」，请确认是否命名不一致。"
                ),
                evidence_json=to_evidence_json(
                    [anchor] if anchor else [],
                    unlocated_reason=None if anchor else "material_name_conflict_unlocated",
                ),
            )
            append_issue(issue)

        for used_key, used_item in used_map.items():
            used_name = norm_name(used_item.get("name"))
            if len(used_name) < 2:
                continue
            for table_key, table_item in table_map.items():
                if used_key == table_key:
                    continue
                table_name = norm_name(table_item.get("name"))
                if len(table_name) < 2:
                    continue
                ratio = SequenceMatcher(None, used_name, table_name).ratio()
                if ratio < 0.95:
                    continue
                anchor = material_anchor_by_code.get(used_key)
                issue = AuditResult(
                    project_id=project_id,
                    audit_version=audit_version,
                    type="material",
                    severity="warning",
                    sheet_no_a=json_data.sheet_no,
                    location=f"材料标注{used_item['code']}",
                    description=(
                        f"图纸中材料「{used_item['name'] or '未命名'}」编号为{used_item['code']}，"
                        f"与材料表中「{table_item['name'] or '未命名'}」编号{table_item['code']}高度相似，"
                        "可能存在编号或命名冲突。"
                    ),
                    evidence_json=to_evidence_json(
                        [anchor] if anchor else [],
                        unlocated_reason=None if anchor else "material_similarity_unlocated",
                    ),
                )
                append_issue(issue)
                break

        try:
            ai_items = asyncio.run(
                _run_material_ai_review(
                    sheet_no=json_data.sheet_no or "",
                    material_table=raw_table,
                    material_used=raw_used,
                )
            )
        except Exception as exc:
            logger.warning("材料 AI 审核降级为规则模式：sheet=%s error=%s", json_data.sheet_no, exc)
            ai_items = []

        for item in ai_items:
            severity = str(item.get("severity") or "warning").strip() or "warning"
            location = str(item.get("location") or f"材料{item.get('material_code') or '?'}").strip()
            description = str(item.get("description") or "").strip()
            if not description:
                continue
            evidence = item.get("evidence") if isinstance(item.get("evidence"), dict) else {}
            code_key = norm_code(
                str(item.get("material_code") or evidence.get("code") or "").strip()
            )
            anchor = material_anchor_by_code.get(code_key)
            issue = AuditResult(
                project_id=project_id,
                audit_version=audit_version,
                type="material",
                severity=severity,
                sheet_no_a=json_data.sheet_no,
                location=location,
                description=description,
                evidence_json=to_evidence_json(
                    [anchor] if anchor else [],
                    unlocated_reason=None if anchor else "material_ai_issue_unlocated",
                ),
            )
            append_issue(issue)

    db.commit()
    return issues
