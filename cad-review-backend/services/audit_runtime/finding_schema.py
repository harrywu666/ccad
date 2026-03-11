"""结构化 Finding 契约与兼容转换。"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


FindingType = Literal["missing_ref", "dim_mismatch", "material_conflict", "index_conflict", "unknown"]
FindingStatus = Literal["confirmed", "suspected", "needs_review"]
GROUNDING_MAX_RETRY = 2


class GroundingRequiredError(ValueError):
    """Finding 必须带精确定位时的校验错误。"""


class Finding(BaseModel):
    """统一的审核发现结构。"""

    model_config = ConfigDict(extra="forbid")

    sheet_no: str = Field(min_length=1)
    location: str = Field(min_length=1)
    rule_id: str = Field(min_length=1)
    finding_type: FindingType
    severity: Literal["error", "warning", "info"]
    status: FindingStatus
    confidence: float = Field(ge=0.0, le=1.0)
    source_agent: str = Field(min_length=1)
    evidence_pack_id: str = Field(min_length=1)
    review_round: int = Field(ge=1)
    triggered_by: Optional[str] = None
    description: str = ""


def _safe_json_loads(payload: Optional[str]) -> Dict[str, Any]:
    if not payload:
        return {}
    try:
        value = json.loads(payload)
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _extract_anchor_list(evidence_json: Optional[str]) -> List[Dict[str, Any]]:
    payload = _safe_json_loads(evidence_json)
    anchors = payload.get("anchors")
    if not isinstance(anchors, list):
        return []
    return [anchor for anchor in anchors if isinstance(anchor, dict)]


def _is_grounded_anchor(anchor: Dict[str, Any]) -> bool:
    region = anchor.get("highlight_region")
    if not isinstance(region, dict):
        return False
    bbox = region.get("bbox_pct")
    if not isinstance(bbox, dict):
        return False
    try:
        width = float(bbox.get("width"))
        height = float(bbox.get("height"))
    except (TypeError, ValueError):
        return False
    return width > 0.0 and height > 0.0


def validate_grounded_evidence_json(
    evidence_json: Optional[str],
    *,
    min_anchor_count: int = 1,
) -> List[Dict[str, Any]]:
    anchors = _extract_anchor_list(evidence_json)
    grounded = [anchor for anchor in anchors if _is_grounded_anchor(anchor)]
    if len(grounded) < min_anchor_count:
        raise GroundingRequiredError("子 Agent 输出的问题缺少可画云线的精确定位")
    return grounded


def default_finding_type(issue_type: Optional[str]) -> FindingType:
    mapping: Dict[str, FindingType] = {
        "index": "index_conflict",
        "dimension": "dim_mismatch",
        "material": "material_conflict",
        "relationship": "missing_ref",
    }
    return mapping.get((issue_type or "").strip().lower(), "unknown")


def default_source_agent(issue_type: Optional[str]) -> str:
    mapping = {
        "index": "index_review_agent",
        "dimension": "dimension_review_agent",
        "material": "material_review_agent",
        "relationship": "relationship_review_agent",
    }
    return mapping.get((issue_type or "").strip().lower(), "audit_agent")


def finding_from_audit_result(item: Any) -> Finding:
    """从现有 AuditResult 兼容构造结构化 Finding。"""

    evidence = _safe_json_loads(getattr(item, "evidence_json", None))
    sheet_no = str(getattr(item, "sheet_no_a", None) or getattr(item, "sheet_no_b", None) or "").strip() or "UNKNOWN"
    location = str(getattr(item, "location", None) or "").strip() or "未定位"
    severity = str(getattr(item, "severity", None) or "warning").strip().lower()
    if severity not in {"error", "warning", "info"}:
        severity = "warning"

    confidence_raw = getattr(item, "confidence", None)
    if confidence_raw is None:
        confidence_raw = evidence.get("confidence", 0.5)
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError):
        confidence = 0.5
    confidence = max(0.0, min(1.0, confidence))

    review_round_raw = getattr(item, "review_round", None)
    if review_round_raw is None:
        review_round_raw = evidence.get("review_round", 1)
    try:
        review_round = int(review_round_raw)
    except (TypeError, ValueError):
        review_round = 1
    review_round = max(1, review_round)

    status = str(getattr(item, "finding_status", None) or "").strip().lower()
    if status not in {"confirmed", "suspected", "needs_review"}:
        if review_round >= 3:
            status = "needs_review"
        elif confidence >= 0.75:
            status = "confirmed"
        else:
            status = "suspected"

    finding_type = str(getattr(item, "finding_type", None) or "").strip().lower()
    if finding_type not in {"missing_ref", "dim_mismatch", "material_conflict", "index_conflict", "unknown"}:
        finding_type = default_finding_type(getattr(item, "type", None))

    rule_id = str(getattr(item, "rule_id", None) or "").strip()
    if not rule_id:
        rule_id = str(evidence.get("rule_id") or f"{(getattr(item, 'type', None) or 'audit').lower()}_rule").strip()

    source_agent = str(getattr(item, "source_agent", None) or "").strip()
    if not source_agent:
        source_agent = str(evidence.get("source_agent") or default_source_agent(getattr(item, "type", None))).strip()

    evidence_pack_id = str(getattr(item, "evidence_pack_id", None) or "").strip()
    if not evidence_pack_id:
        evidence_pack_id = str(evidence.get("evidence_pack_id") or "legacy_pack").strip()

    triggered_by = str(getattr(item, "triggered_by", None) or evidence.get("triggered_by") or "").strip() or None
    description = str(getattr(item, "description", None) or "").strip()

    return Finding(
        sheet_no=sheet_no,
        location=location,
        rule_id=rule_id,
        finding_type=finding_type,  # type: ignore[arg-type]
        severity=severity,  # type: ignore[arg-type]
        status=status,  # type: ignore[arg-type]
        confidence=confidence,
        source_agent=source_agent,
        evidence_pack_id=evidence_pack_id,
        review_round=review_round,
        triggered_by=triggered_by,
        description=description,
    )


def merge_finding_into_evidence_json(
    evidence_json: Optional[str],
    finding: Finding,
) -> str:
    payload = _safe_json_loads(evidence_json)
    payload["finding"] = finding.model_dump()
    payload.setdefault("confidence", finding.confidence)
    payload.setdefault("review_round", finding.review_round)
    payload.setdefault("rule_id", finding.rule_id)
    payload.setdefault("source_agent", finding.source_agent)
    payload.setdefault("evidence_pack_id", finding.evidence_pack_id)
    if finding.triggered_by:
        payload.setdefault("triggered_by", finding.triggered_by)
    try:
        grounded = validate_grounded_evidence_json(json.dumps(payload, ensure_ascii=False))
    except GroundingRequiredError:
        grounded = []
    if grounded:
        payload["grounding"] = {
            "status": "grounded",
            "anchor_count": len(grounded),
        }
    return json.dumps(payload, ensure_ascii=False)


def apply_finding_to_audit_result(
    item: Any,
    finding: Finding,
    *,
    require_grounding: bool = False,
    min_anchor_count: int = 1,
) -> Any:
    """把结构化 Finding 回填到 AuditResult 兼容字段。"""

    item.rule_id = finding.rule_id
    item.finding_type = finding.finding_type
    item.finding_status = finding.status
    item.source_agent = finding.source_agent
    item.evidence_pack_id = finding.evidence_pack_id
    item.review_round = finding.review_round
    item.triggered_by = finding.triggered_by
    item.confidence = finding.confidence
    item.evidence_json = merge_finding_into_evidence_json(
        getattr(item, "evidence_json", None),
        finding,
    )
    if require_grounding:
        validate_grounded_evidence_json(item.evidence_json, min_anchor_count=min_anchor_count)
    return item
