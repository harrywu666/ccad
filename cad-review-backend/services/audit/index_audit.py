"""Index audit implementation."""

from __future__ import annotations

import re
from collections import defaultdict
from typing import Any, Callable, Dict, List, Optional

from domain.sheet_normalization import normalize_index_no, normalize_sheet_no
from models import AuditResult, Catalog, JsonData
from services.audit.common import build_anchor, to_evidence_json
from services.audit.issue_preview import ensure_issue_drawing_matches
from services.layout_json_service import load_enriched_layout_json
from services.skill_pack_service import (
    build_index_alias_map,
    canonicalize_index_key,
    canonicalize_sheet_key,
    load_active_skill_rules,
)


def _build_sheet_validator(catalog_sheet_nos: List[str]) -> Callable[[str], bool]:
    """从目录图号列表中学习当前项目的图号命名规律，返回一个校验函数。

    校验函数返回 True 表示 target 看起来像本项目的图号；
    返回 False 表示 target 更像分图号/假阳性，应跳过。
    """
    valid_nos = [s.strip() for s in catalog_sheet_nos if s and s.strip()]
    if not valid_nos:
        return lambda _: True  # 没有目录信息，保守起见全部放行

    # 学习最短图号长度（容错 -2，允许略短的缩写写法）
    min_len = max(2, min(len(s) for s in valid_nos) - 2)

    # 学习是否需要分隔符（- . _）：70% 以上有分隔符则认为本项目图号带分隔符
    with_sep = sum(1 for s in valid_nos if re.search(r"[-._]", s))
    separator_required = with_sep >= len(valid_nos) * 0.7

    # 学习常见起始字母前缀（如 A、T、FP、PL 等）
    prefix_re = re.compile(r"^([A-Za-z]{1,4})")
    prefixes: set[str] = set()
    for s in valid_nos:
        m = prefix_re.match(s)
        if m:
            prefixes.add(m.group(1).upper())

    def validator(target: str) -> bool:
        t = (target or "").strip()
        if not t:
            return False
        # 比最短图号还短很多 → 几乎不可能是图号
        if len(t) < min_len:
            return False
        # 项目图号普遍带分隔符，但 target 没有 → 分图号假阳性
        if separator_required and not re.search(r"[-._]", t):
            return False
        # 项目有明确字母前缀，但 target 全是数字 → 不符合项目图号格式
        if prefixes and not re.match(r"[A-Za-z]", t) and re.fullmatch(r"\d+", t):
            return False
        return True

    return validator


# 功能说明：从属性列表中按标签键提取值
def _pick_attr_value(attrs: list[dict[str, Any]], keys: tuple[str, ...]) -> str:
    key_set = {key.upper() for key in keys}
    for attr in attrs:
        tag = str(attr.get("tag") or "").strip().upper()
        if tag in key_set:
            return str(attr.get("value") or "").strip()
    return ""


def _collect_target_reference_labels(
    data: Dict[str, Any],
    alias_map: Dict[str, str],
) -> set[str]:
    labels: set[str] = set()

    for idx in data.get("indexes", []) or []:
        label_key = canonicalize_index_key(str(idx.get("index_no") or "").strip(), alias_map)
        if label_key:
            labels.add(label_key)

    for title in data.get("title_blocks", []) or []:
        attrs = title.get("attrs") or []
        raw_label = (
            str(title.get("title_label") or "").strip()
            or _pick_attr_value(attrs, ("_ACM-TITLELABEL", "TITLELABEL", "TITLE_LABEL"))
        )
        label_key = canonicalize_index_key(raw_label, alias_map)
        if label_key:
            labels.add(label_key)

    for detail in data.get("detail_titles", []) or []:
        label_key = canonicalize_index_key(str(detail.get("label") or "").strip(), alias_map)
        if label_key:
            labels.add(label_key)

    return labels


# 功能说明：创建索引审核结果对象
def _issue_index(
    project_id: str,
    audit_version: int,
    severity: str,
    sheet_no_a: Optional[str],
    sheet_no_b: Optional[str],
    location: str,
    description: str,
    evidence_json: Optional[str] = None,
) -> AuditResult:
    return AuditResult(
        project_id=project_id,
        audit_version=audit_version,
        type="index",
        severity=severity,
        sheet_no_a=sheet_no_a,
        sheet_no_b=sheet_no_b,
        location=location,
        description=description,
        evidence_json=evidence_json,
    )


# 功能说明：执行图纸索引关系审核，检查索引指向的有效性和一致性
def audit_indexes(
    project_id: str,
    audit_version: int,
    db,
    source_sheet_filters: Optional[List[str]] = None,
) -> List[AuditResult]:
    alias_map = build_index_alias_map(load_active_skill_rules(db, skill_type="index"))

    # 从目录中学习本项目的图号命名规律，用于过滤分图号假阳性
    catalog_sheet_nos = [
        c.sheet_no
        for c in db.query(Catalog).filter(
            Catalog.project_id == project_id,
            Catalog.status == "locked",
            Catalog.sheet_no.isnot(None),
        ).all()
        if c.sheet_no
    ]
    is_plausible_sheet = _build_sheet_validator(catalog_sheet_nos)

    allowed_source_keys: Optional[set[str]] = None
    if source_sheet_filters:
        allowed_source_keys = {
            canonicalize_sheet_key(item, alias_map)
            for item in source_sheet_filters
            if canonicalize_sheet_key(item, alias_map)
        }
        if not allowed_source_keys:
            return []

    json_list = (
        db.query(JsonData)
        .filter(
            JsonData.project_id == project_id,
            JsonData.is_latest == 1,
        )
        .all()
    )

    sheet_map: Dict[str, str] = {}
    sheet_index_defs: Dict[str, set[str]] = defaultdict(set)
    sheet_detail_label_defs: Dict[str, set[str]] = defaultdict(set)
    forward_links: List[Dict[str, Any]] = []
    orphan_candidates: List[Dict[str, Any]] = []
    sheet_index_anchor_map: Dict[str, Dict[str, Dict[str, Any]]] = defaultdict(dict)

    for json_data in json_list:
        json_path = json_data.json_path or ""
        if not json_path:
            continue

        data = load_enriched_layout_json(json_path)
        if not data:
            continue

        raw_sheet_no = (json_data.sheet_no or data.get("sheet_no") or "").strip()
        if not raw_sheet_no:
            continue
        src_key = canonicalize_sheet_key(raw_sheet_no, alias_map)
        if not src_key:
            continue
        sheet_map.setdefault(src_key, raw_sheet_no)

        indexes = data.get("indexes", []) or []
        for idx in indexes:
            raw_index_no = str(idx.get("index_no", "") or "").strip()
            raw_target_sheet = str(idx.get("target_sheet", "") or "").strip()
            idx_key = canonicalize_index_key(raw_index_no, alias_map)
            tgt_key = canonicalize_sheet_key(raw_target_sheet, alias_map)
            source_anchor = build_anchor(
                role="source",
                sheet_no=raw_sheet_no,
                grid=str(idx.get("grid") or "").strip(),
                global_pct=idx.get("global_pct") if isinstance(idx.get("global_pct"), dict) else None,
                confidence=1.0,
                origin="index",
            )

            if idx_key:
                sheet_index_defs[src_key].add(idx_key)
                if source_anchor and idx_key not in sheet_index_anchor_map[src_key]:
                    sheet_index_anchor_map[src_key][idx_key] = source_anchor

            # 本图索引（下方为短横线）：不涉及跨图验证，直接跳过
            if idx.get("same_sheet"):
                continue

            if not idx_key and not tgt_key:
                continue

            # 用目录学到的图号格式校验 target_sheet：
            # 若 target 不像本项目的图号（如分图号 "A"、"01"），直接丢弃，不报错
            if raw_target_sheet and not is_plausible_sheet(raw_target_sheet):
                continue

            row = {
                "source_raw": raw_sheet_no,
                "source_key": src_key,
                "index_raw": raw_index_no,
                "index_key": idx_key,
                "target_raw": raw_target_sheet,
                "target_key": tgt_key,
                "source_anchor": source_anchor,
            }
            if tgt_key:
                forward_links.append(row)
            elif idx_key:
                orphan_candidates.append(row)

        sheet_detail_label_defs[src_key].update(_collect_target_reference_labels(data, alias_map))

    issues: List[AuditResult] = []
    existing_sheets = set(sheet_map.keys())
    referenced_targets = {
        (item["target_key"], item["index_key"])
        for item in forward_links
        if item["target_key"] and item["index_key"]
    }
    reverse_link_keys = {
        (item["source_key"], item["target_key"])
        for item in forward_links
        if item["source_key"] and item["target_key"]
    }

    for rel in forward_links:
        if allowed_source_keys is not None and rel["source_key"] not in allowed_source_keys:
            continue
        tgt_key = rel["target_key"]
        if tgt_key not in existing_sheets:
            anchors = [rel["source_anchor"]] if rel.get("source_anchor") else []
            issue = _issue_index(
                project_id=project_id,
                audit_version=audit_version,
                severity="error",
                sheet_no_a=rel["source_raw"],
                sheet_no_b=rel["target_raw"] or None,
                location=f"索引{rel['index_raw'] or '?'}",
                description=(
                    f"图纸{rel['source_raw']}中的索引{rel['index_raw'] or '?'}"
                    f" 指向 {rel['target_raw'] or '未知图号'}，但目录/数据中不存在该目标图。"
                ),
                evidence_json=to_evidence_json(
                    anchors, unlocated_reason=None if anchors else "missing_target_sheet"
                ),
            )
            db.add(issue)
            db.flush()
            ensure_issue_drawing_matches(issue, db)
            issues.append(issue)

    for rel in forward_links:
        if allowed_source_keys is not None and rel["source_key"] not in allowed_source_keys:
            continue
        tgt_key = rel["target_key"]
        idx_key = rel["index_key"]
        if not tgt_key or tgt_key not in existing_sheets or not idx_key:
            continue
        target_index_defs = sheet_index_defs.get(tgt_key, set())
        target_detail_labels = sheet_detail_label_defs.get(tgt_key, set())
        if idx_key not in target_index_defs and idx_key not in target_detail_labels:
            target_raw = sheet_map.get(tgt_key, rel["target_raw"] or "")
            anchors = [rel["source_anchor"]] if rel.get("source_anchor") else []
            issue = _issue_index(
                project_id=project_id,
                audit_version=audit_version,
                severity="error",
                sheet_no_a=rel["source_raw"],
                sheet_no_b=target_raw or rel["target_raw"] or None,
                location=f"索引{rel['index_raw'] or '?'}",
                description=(
                    f"图纸{rel['source_raw']}中的索引{rel['index_raw'] or '?'} 指向 {target_raw or rel['target_raw'] or '目标图'}，"
                    "但目标图中未找到同编号索引。"
                ),
                evidence_json=to_evidence_json(
                    anchors, unlocated_reason=None if anchors else "missing_target_index_no"
                ),
            )
            db.add(issue)
            db.flush()
            ensure_issue_drawing_matches(issue, db)
            issues.append(issue)

    for rel in forward_links:
        if allowed_source_keys is not None and rel["source_key"] not in allowed_source_keys:
            continue
        src_key = rel["source_key"]
        tgt_key = rel["target_key"]
        if not src_key or not tgt_key or src_key == tgt_key or tgt_key not in existing_sheets:
            continue
        if rel["index_key"] and rel["index_key"] in sheet_detail_label_defs.get(tgt_key, set()):
            continue
        if (tgt_key, src_key) in reverse_link_keys:
            continue
        target_raw = sheet_map.get(tgt_key, rel["target_raw"] or "")
        anchors: List[Dict[str, Any]] = []
        if rel.get("source_anchor"):
            anchors.append(rel["source_anchor"])
        target_anchor = sheet_index_anchor_map.get(tgt_key, {}).get(rel["index_key"] or "")
        if target_anchor:
            target_anchor = dict(target_anchor)
            target_anchor["role"] = "target"
            anchors.append(target_anchor)
        issue = _issue_index(
            project_id=project_id,
            audit_version=audit_version,
            severity="warning",
            sheet_no_a=rel["source_raw"],
            sheet_no_b=target_raw or rel["target_raw"] or None,
            location=f"索引{rel['index_raw'] or '?'}",
            description=(
                f"图纸{rel['source_raw']}指向{target_raw or rel['target_raw'] or '目标图'}，"
                f"但未发现{target_raw or rel['target_raw'] or '目标图'}反向指向{rel['source_raw']}，请确认索引链闭合性。"
            ),
            evidence_json=to_evidence_json(
                anchors, unlocated_reason=None if anchors else "missing_reverse_link"
            ),
        )
        db.add(issue)
        db.flush()
        ensure_issue_drawing_matches(issue, db)
        issues.append(issue)

    for orphan in orphan_candidates:
        if allowed_source_keys is not None and orphan["source_key"] not in allowed_source_keys:
            continue
        pair = (orphan["source_key"], orphan["index_key"])
        if pair in referenced_targets:
            continue
        anchors = [orphan["source_anchor"]] if orphan.get("source_anchor") else []
        issue = _issue_index(
            project_id=project_id,
            audit_version=audit_version,
            severity="warning",
            sheet_no_a=orphan["source_raw"],
            sheet_no_b=None,
            location=f"索引{orphan['index_raw'] or '?'}",
            description=(
                f"图纸{orphan['source_raw']}中的索引{orphan['index_raw'] or '?'} 未标注目标图号，且未被其他图纸引用，可能是孤立索引。"
            ),
            evidence_json=to_evidence_json(
                anchors, unlocated_reason=None if anchors else "orphan_index_without_target"
            ),
        )
        db.add(issue)
        db.flush()
        ensure_issue_drawing_matches(issue, db)
        issues.append(issue)

    db.commit()
    return issues
