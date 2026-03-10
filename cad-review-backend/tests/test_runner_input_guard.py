from __future__ import annotations

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit import index_audit, relationship_discovery
from services.audit_runtime.contracts import EvidencePack, EvidencePackType, EvidencePlanItem
from services.audit_runtime.runner_types import RunnerTurnResult


class _FakeRunner:
    def __init__(self) -> None:
        self.calls = 0

    async def run_stream(self, request, *args, **kwargs):  # noqa: ANN001
        self.calls += 1
        return RunnerTurnResult(
            provider_name="fake",
            output=[
                {
                    "source": request.meta.get("candidate_source_sheet_no") or "A-01",
                    "target": request.meta.get("candidate_target_sheet_no") or "A-02",
                    "confidence": 0.92,
                    "relation": "ai_visual",
                }
            ],
            status="ok",
            raw_output="[]",
            subsession_key="fake",
        )


class _FakeEvidenceService:
    async def get_evidence_pack(self, request):  # noqa: ANN001
        return EvidencePack(
            pack_type=request.pack_type,
            images={"overview": b"fake-image"},
            source_pdf_path=request.source_pdf_path or "",
            source_page_index=int(request.source_page_index or 0),
            target_pdf_path=request.target_pdf_path,
            target_page_index=request.target_page_index,
        )


@dataclass
class _FakeIssue:
    description: str = "需要 AI 复核"
    severity: str = "warning"


class _FakeQuery:
    def filter(self, *_args, **_kwargs):
        return self

    def all(self):
        return []


class _FakeDb:
    def query(self, *_args, **_kwargs):
        return _FakeQuery()


def _build_plan_item() -> EvidencePlanItem:
    return EvidencePlanItem(
        task_type="relationship",
        pack_type=EvidencePackType.PAIRED_OVERVIEW_PACK,
        source_sheet_no="A-01",
        target_sheet_no="A-02",
        round_index=1,
        reason="test",
    )


def test_relationship_candidate_self_pair_is_skipped_without_ai_call(monkeypatch):
    fake_runner = _FakeRunner()

    monkeypatch.setattr(relationship_discovery, "plan_lite", lambda **_kwargs: [_build_plan_item()])
    monkeypatch.setattr(relationship_discovery, "_get_relationship_runner", lambda *_args, **_kwargs: fake_runner)

    result = asyncio.run(
        relationship_discovery._discover_relationship_task_v2(
            source_sheet={
                "sheet_no": "A-01",
                "sheet_name": "平面图",
                "pdf_path": "/tmp/source.pdf",
                "page_index": 0,
            },
            target_sheet={
                "sheet_no": "A-01",
                "sheet_name": "平面图",
                "pdf_path": "/tmp/target.pdf",
                "page_index": 1,
            },
            call_kimi=lambda **kwargs: None,
            project_id="proj-input-guard",
            audit_version=1,
            evidence_service=_FakeEvidenceService(),
            skill_profile={},
            feedback_profile={},
        )
    )

    assert result == []
    assert fake_runner.calls == 0


def test_relationship_candidate_without_required_images_is_skipped_without_ai_call(monkeypatch):
    fake_runner = _FakeRunner()

    monkeypatch.setattr(relationship_discovery, "plan_lite", lambda **_kwargs: [_build_plan_item()])
    monkeypatch.setattr(relationship_discovery, "_get_relationship_runner", lambda *_args, **_kwargs: fake_runner)

    result = asyncio.run(
        relationship_discovery._discover_relationship_task_v2(
            source_sheet={
                "sheet_no": "A-01",
                "sheet_name": "平面图",
                "pdf_path": "",
                "page_index": 0,
            },
            target_sheet={
                "sheet_no": "A-02",
                "sheet_name": "立面图",
                "pdf_path": "/tmp/target.pdf",
                "page_index": 1,
            },
            call_kimi=lambda **kwargs: None,
            project_id="proj-input-guard",
            audit_version=1,
            evidence_service=_FakeEvidenceService(),
            skill_profile={},
            feedback_profile={},
        )
    )

    assert result == []
    assert fake_runner.calls == 0


def test_index_review_candidate_with_blank_sheet_no_is_skipped_without_ai_call(monkeypatch):
    fake_calls = {"count": 0}

    async def _fake_run_index_ai_review(*_args, **_kwargs):
        fake_calls["count"] += 1
        return {"decision": "accept", "confidence": 0.93}

    monkeypatch.setattr(index_audit, "_run_index_ai_review", _fake_run_index_ai_review)
    monkeypatch.setattr(index_audit, "append_run_event", lambda *_args, **_kwargs: None)

    result = asyncio.run(
        index_audit._review_index_issue_candidates_async(
            "proj-input-guard",
            _FakeDb(),
            [
                {
                    "issue": _FakeIssue(),
                    "review_kind": "missing_reverse_link",
                    "source_sheet_no": "",
                    "target_sheet_no": "A-02",
                    "source_key": "",
                    "target_key": "A-02",
                    "index_no": "1",
                }
            ],
            audit_version=1,
            skill_profile={},
            feedback_profile={},
        )
    )

    assert result == []
    assert fake_calls["count"] == 0
