from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.review_kernel.llm_intervention import (  # noqa: E402
    call_with_backoff,
    disambiguate_reference_bindings,
    get_llm_stage_switch_snapshot,
    polish_issue_writing,
)
from services.review_kernel.policy import ProjectPolicy  # noqa: E402


def _build_ir() -> dict:
    cand1 = {
        "candidate_id": "cand-1",
        "sheet_no": "A4.01",
        "score": 0.79,
        "is_known_sheet": True,
        "basis": ["token_exact"],
    }
    cand2 = {
        "candidate_id": "cand-2",
        "sheet_no": "A4.02",
        "score": 0.78,
        "is_known_sheet": True,
        "basis": ["token_partial"],
    }
    return {
        "semantic_layer": {
            "references": [
                {
                    "ref_id": "ref-1",
                    "target_sheet_no": "A4.01",
                    "selected_candidate_id": "cand-1",
                    "target_missing": False,
                    "confidence": 0.79,
                    "candidate_bindings": [cand1, cand2],
                    "needs_llm_disambiguation": True,
                    "ambiguity_flags": ["multi_candidate_close_score"],
                }
            ],
            "candidate_relations": [
                {
                    "relation_id": "ref-1",
                    "raw_label": "A1/A4.01",
                    "candidate_bindings": [cand1, cand2],
                    "selected_candidate_id": "cand-1",
                    "needs_llm_disambiguation": True,
                    "ambiguity_flags": ["multi_candidate_close_score"],
                    "confidence": 0.79,
                }
            ],
        }
    }


def _build_slice(ir_package: dict) -> dict:
    return {
        "context_slice_id": "cs-1",
        "slice_type": "relation_disambiguation",
        "payload": {
            "logical_sheet": {"logical_sheet_id": "ls-1", "sheet_number": "A1.01"},
            "review_view": {"review_view_id": "rv-1"},
            "candidate_relations": ir_package["semantic_layer"]["candidate_relations"],
            "dimension_evidence": [
                {
                    "display_value": 1000,
                    "confidence": 0.9,
                }
            ],
            "degradation_notices": [],
        },
    }


def test_disambiguation_program_first_without_llm(monkeypatch):
    monkeypatch.delenv("REVIEW_KERNEL_LLM_ENABLED", raising=False)
    ir_package = _build_ir()
    trace = disambiguate_reference_bindings(ir_package, _build_slice(ir_package))
    assert trace["llm_used"] is False
    assert ir_package["semantic_layer"]["references"][0]["selected_candidate_id"] == "cand-1"
    assert ir_package["semantic_layer"]["references"][0]["target_sheet_no"] == "A4.01"


def test_disambiguation_allows_llm_to_select_existing_candidate(monkeypatch):
    monkeypatch.setenv("REVIEW_KERNEL_LLM_ENABLED", "1")
    monkeypatch.setenv("REVIEW_KERNEL_LLM_DISAMBIGUATION_ENABLED", "1")
    ir_package = _build_ir()

    def fake_llm(_system_prompt: str, _user_prompt: str, _max_tokens: int):
        return [
            {
                "relation_id": "ref-1",
                "candidate_id": "cand-2",
                "confidence": 0.82,
                "reason": "target_sheet更贴近节点语义",
            }
        ]

    trace = disambiguate_reference_bindings(
        ir_package,
        _build_slice(ir_package),
        llm_call=fake_llm,
    )
    assert trace["llm_used"] is True
    assert ir_package["semantic_layer"]["references"][0]["selected_candidate_id"] == "cand-2"
    assert ir_package["semantic_layer"]["references"][0]["target_sheet_no"] == "A4.02"


def test_llm_stage_switch_snapshot(monkeypatch):
    monkeypatch.setenv("REVIEW_KERNEL_LLM_ENABLED", "1")
    monkeypatch.setenv("REVIEW_KERNEL_LLM_WEAK_ASSIST_ENABLED", "0")
    monkeypatch.setenv("REVIEW_KERNEL_LLM_DISAMBIGUATION_ENABLED", "1")
    monkeypatch.setenv("REVIEW_KERNEL_LLM_REPORT_WRITING_ENABLED", "1")
    monkeypatch.setenv("KIMI_PROVIDER", "openrouter")

    snapshot = get_llm_stage_switch_snapshot()
    assert snapshot["global_enabled"] is True
    assert snapshot["provider"] == "openrouter"
    assert snapshot["weak_assist_enabled"] is False
    assert snapshot["disambiguation_enabled"] is True
    assert snapshot["report_writing_enabled"] is True


def test_disambiguation_accepts_wrapped_list_response(monkeypatch):
    monkeypatch.setenv("REVIEW_KERNEL_LLM_ENABLED", "1")
    monkeypatch.setenv("REVIEW_KERNEL_LLM_DISAMBIGUATION_ENABLED", "1")
    ir_package = _build_ir()

    def fake_llm(_system_prompt: str, _user_prompt: str, _max_tokens: int):
        return {
            "relations": [
                {
                    "relation_id": "ref-1",
                    "candidate_id": "cand-2",
                    "reason": "wrapped response",
                }
            ]
        }

    trace = disambiguate_reference_bindings(
        ir_package,
        _build_slice(ir_package),
        llm_call=fake_llm,
    )
    assert trace["llm_used"] is True
    assert ir_package["semantic_layer"]["references"][0]["selected_candidate_id"] == "cand-2"


def test_report_writing_accepts_wrapped_list_response(monkeypatch):
    monkeypatch.setenv("REVIEW_KERNEL_LLM_ENABLED", "1")
    monkeypatch.setenv("REVIEW_KERNEL_LLM_REPORT_WRITING_ENABLED", "1")

    issues = [
        {
            "issue_id": "ISS-1",
            "title": "旧标题",
            "description": "旧描述",
            "evidence": {"primary_object_id": "DIM-1"},
            "generated_by": "rule_engine",
        }
    ]
    report_slice = {
        "payload": {
            "logical_sheet": {"logical_sheet_id": "ls-1"},
            "review_view": {"review_view_id": "rv-1"},
            "issues": issues,
        }
    }

    def fake_llm(_system_prompt: str, _user_prompt: str, _max_tokens: int):
        return {
            "issues": [
                {
                    "issue_id": "ISS-1",
                    "title": "新标题",
                    "description": "新描述",
                    "suggested_fix": "建议修复",
                }
            ]
        }

    trace = polish_issue_writing(issues, report_slice, llm_call=fake_llm)
    assert trace["llm_used"] is True
    assert trace["updated"] == 1
    assert issues[0]["title"] == "新标题"
    assert issues[0]["description"] == "新描述"
    assert issues[0]["suggested_fix"] == "建议修复"


def test_report_writing_uses_policy_default_audience(monkeypatch):
    monkeypatch.setenv("REVIEW_KERNEL_LLM_ENABLED", "1")
    monkeypatch.setenv("REVIEW_KERNEL_LLM_REPORT_WRITING_ENABLED", "1")
    monkeypatch.setenv("REVIEW_KERNEL_DEFAULT_AUDIENCE", "supervisor")

    issues = [
        {
            "issue_id": "ISS-2",
            "title": "旧标题",
            "description": "旧描述",
            "evidence": {"primary_object_id": "DIM-2"},
            "generated_by": "rule_engine",
        }
    ]
    report_slice = {
        "payload": {
            "logical_sheet": {"logical_sheet_id": "ls-1"},
            "review_view": {"review_view_id": "rv-1"},
            "issues": issues,
        }
    }

    captured = {}

    def fake_llm(_system_prompt: str, user_prompt: str, _max_tokens: int):
        captured["audience"] = json.loads(user_prompt)["audience"]
        return [{"issue_id": "ISS-2", "title": "新标题", "description": "新描述"}]

    trace = polish_issue_writing(issues, report_slice, llm_call=fake_llm)
    assert trace["llm_used"] is True
    assert captured["audience"] == "supervisor"


def test_call_with_backoff_respects_retry_limit():
    attempts = {"count": 0}

    async def flaky():
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise RuntimeError("429 too many requests")
        return {"ok": True}

    policy = ProjectPolicy(rate_limit_retry_max=3)
    result = asyncio.run(call_with_backoff(flaky, policy))
    assert result == {"ok": True}
    assert attempts["count"] == 3
