"""终审与最终问题的最小结构化契约。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class PctPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0.0, le=100.0)
    y: float = Field(ge=0.0, le=100.0)


class BBoxPct(BaseModel):
    model_config = ConfigDict(extra="forbid")

    x: float = Field(ge=0.0, le=100.0)
    y: float = Field(ge=0.0, le=100.0)
    width: float = Field(gt=0.0, le=100.0)
    height: float = Field(gt=0.0, le=100.0)


class HighlightRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    shape: str = Field(min_length=1)
    bbox_pct: BBoxPct

    @field_validator("shape", mode="before")
    @classmethod
    def _validate_shape(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("shape must not be empty")
        return text


class AnchorPayload(BaseModel):
    model_config = ConfigDict(extra="allow")

    sheet_no: str = Field(min_length=1)
    role: str = Field(min_length=1)
    global_pct: PctPoint | None = None
    highlight_region: HighlightRegion | None = None

    @field_validator("sheet_no", "role", mode="before")
    @classmethod
    def _validate_required_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be empty")
        return text

    def has_location_evidence(self) -> bool:
        return self.global_pct is not None or self.highlight_region is not None


class FinalIssue(BaseModel):
    model_config = ConfigDict(extra="forbid")

    issue_code: str = Field(min_length=1)
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    severity: Literal["error", "warning", "info"]
    finding_type: Literal["missing_ref", "dim_mismatch", "material_conflict", "index_conflict", "unknown"]
    disposition: Literal["accepted", "rejected", "needs_more_evidence", "redispatch"]
    source_agent: str = Field(min_length=1)
    source_assignment_id: str = Field(min_length=1)
    source_sheet_no: str = Field(min_length=1)
    target_sheet_nos: list[str]
    location_text: str = Field(min_length=1)
    recommendation: str | None = None
    evidence_pack_id: str = Field(min_length=1)
    anchors: list[AnchorPayload]
    confidence: float = Field(ge=0.0, le=1.0)
    review_round: int = Field(ge=1)
    organizer_markdown_block: str = Field(min_length=1)

    @field_validator(
        "issue_code",
        "title",
        "description",
        "source_agent",
        "source_assignment_id",
        "source_sheet_no",
        "location_text",
        "evidence_pack_id",
        "organizer_markdown_block",
        mode="before",
    )
    @classmethod
    def _validate_required_text(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("value must not be empty")
        return text

    @field_validator("target_sheet_nos", mode="before")
    @classmethod
    def _validate_target_sheet_nos(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("target_sheet_nos must be a list")
        normalized = [str(item or "").strip() for item in value]
        if any(not item for item in normalized):
            raise ValueError("target_sheet_nos items must not be empty")
        return normalized

    @model_validator(mode="after")
    def _validate_grounding(self) -> "FinalIssue":
        if not self.anchors:
            raise ValueError("FinalIssue requires grounded anchors")
        if not any(anchor.has_location_evidence() for anchor in self.anchors):
            raise ValueError("FinalIssue requires at least one anchor with grounding coordinates")
        return self

    @field_validator("recommendation", mode="before")
    @classmethod
    def _validate_optional_text(cls, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value or "").strip()
        return text or None


__all__ = ["PctPoint", "BBoxPct", "HighlightRegion", "AnchorPayload", "FinalIssue"]
