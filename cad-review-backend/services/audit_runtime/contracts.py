"""审图运行时共享契约。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any, Dict, Optional


class EvidencePackType(StrEnum):
    OVERVIEW_PACK = "overview_pack"
    PAIRED_OVERVIEW_PACK = "paired_overview_pack"
    FOCUS_PACK = "focus_pack"
    DEEP_PACK = "deep_pack"


@dataclass(frozen=True)
class EvidenceRequest:
    pack_type: EvidencePackType
    source_pdf_path: str
    source_page_index: int
    target_pdf_path: Optional[str] = None
    target_page_index: Optional[int] = None
    focus_hint: Optional[str] = None
    render_options: Dict[str, float | int] = field(default_factory=dict)


@dataclass
class EvidencePack:
    pack_type: EvidencePackType
    images: Dict[str, bytes]
    source_pdf_path: str
    source_page_index: int
    target_pdf_path: Optional[str] = None
    target_page_index: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "pack_type": self.pack_type.value,
            "image_keys": list(self.images.keys()),
            "source_pdf_path": self.source_pdf_path,
            "source_page_index": self.source_page_index,
            "target_pdf_path": self.target_pdf_path,
            "target_page_index": self.target_page_index,
        }


@dataclass(frozen=True)
class EvidencePlanItem:
    task_type: str
    pack_type: EvidencePackType
    source_sheet_no: str
    target_sheet_no: Optional[str]
    round_index: int
    reason: str
    requires_visual: bool = True
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["pack_type"] = self.pack_type.value
        return payload
