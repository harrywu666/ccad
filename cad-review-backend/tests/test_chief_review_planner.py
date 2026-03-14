from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
import importlib
import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.chief_review_planner import plan_chief_review_hypotheses  # noqa: E402


def test_chief_review_planner_uses_chief_agent_prompt():
    result = plan_chief_review_hypotheses(
        project_id="proj-chief",
        audit_version=7,
        memory={"confirmed_links": []},
        sheet_graph=SimpleNamespace(sheet_types={"A1-01": "plan"}, linked_targets={"A1-01": ["A4-01"]}),
    )

    assert result.meta["prompt_source"] == "chief_agent"
    assert result.meta["agent_id"] == "chief_review"
    assert result.meta["planner_source"] == "chief_agent"
    assert "Chief Review Agent" in result.prompt_bundle.system_prompt
    assert result.items[0]["context"]["suggested_worker_kind"] == "spatial_consistency"
    assert result.meta["planner_mode"] == "chief_resource_planner"


def test_chief_review_planner_returns_empty_when_no_linked_targets():
    result = plan_chief_review_hypotheses(
        project_id="proj-chief",
        audit_version=8,
        memory={"confirmed_links": []},
        sheet_graph=SimpleNamespace(sheet_types={}, linked_targets={}),
    )

    assert result.items == []
    assert result.meta["hypothesis_count"] == 0


def test_chief_review_planner_surfaces_chief_recheck_queue():
    result = plan_chief_review_hypotheses(
        project_id="proj-chief",
        audit_version=9,
        memory={
            "confirmed_links": [],
            "chief_recheck_queue": [
                {
                    "id": "hyp-recheck",
                    "topic": "节点归属复核",
                    "objective": "主审回看 A1-01 -> A4-01",
                    "source_sheet_no": "A1-01",
                    "target_sheet_nos": ["A4-01"],
                    "worker_kind": "node_host_binding",
                    "context": {"suggested_worker_kind": "node_host_binding"},
                }
            ],
        },
        sheet_graph=SimpleNamespace(sheet_types={}, linked_targets={}),
    )

    assert result.chief_recheck_queue[0]["id"] == "hyp-recheck"
    assert result.meta["chief_recheck_count"] == 1


def test_chief_review_planner_requires_chief_review_assets(monkeypatch):
    planner = importlib.import_module("services.audit_runtime.chief_review_planner")

    monkeypatch.setattr(
        planner,
        "load_agent_asset_bundle",
        lambda agent_id: SimpleNamespace(
            agent_markdown="# Chief Review Agent\n",
            soul_markdown="",
            memory_markdown="# Chief Review Memory\n",
        ),
    )

    with pytest.raises(ValueError, match="chief_review_rules_missing"):
        planner.plan_chief_review_hypotheses(
            project_id="proj-chief",
            audit_version=10,
            memory={},
            sheet_graph=SimpleNamespace(
                sheet_types={"A1-01": "plan", "A4-01": "detail"},
                linked_targets={"A1-01": ["A4-01"]},
            ),
        )
