from __future__ import annotations

import importlib
import sys
from pathlib import Path
from types import SimpleNamespace


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _ctx(sheet_no: str, sheet_name: str):
    return SimpleNamespace(
        sheet_no=sheet_no,
        sheet_name=sheet_name,
        meta_json="{}",
    )


def _edge(source_sheet_no: str, target_sheet_no: str, edge_type: str = "index_ref"):
    return SimpleNamespace(
        source_sheet_no=source_sheet_no,
        target_sheet_no=target_sheet_no,
        edge_type=edge_type,
        confidence=1.0,
        evidence_json='{"mention_count": 1}',
    )


def test_build_sheet_graph_groups_plan_ceiling_elevation_detail():
    sheet_graph_builder = importlib.import_module("services.audit_runtime.sheet_graph_builder")

    graph = sheet_graph_builder.build_sheet_graph(
        sheet_contexts=[
            _ctx("A1-01", "首层平面图"),
            _ctx("A2-01", "天花布置图"),
            _ctx("A3-01", "立面图"),
            _ctx("A4-01", "节点详图"),
        ],
        sheet_edges=[
            _edge("A1-01", "A4-01"),
            _edge("A2-01", "A3-01"),
        ],
    )

    assert graph.sheet_types["A1-01"] == "plan"
    assert graph.sheet_types["A2-01"] == "ceiling"
    assert graph.sheet_types["A3-01"] == "elevation"
    assert graph.sheet_types["A4-01"] == "detail"
    assert graph.linked_targets["A1-01"] == ["A4-01"]


def test_sheet_graph_semantic_builder_uses_llm_to_confirm_sheet_types():
    candidates_builder = importlib.import_module("services.audit_runtime.sheet_graph_candidates_builder")
    semantic_builder = importlib.import_module("services.audit_runtime.sheet_graph_semantic_builder")

    candidates = candidates_builder.build_sheet_graph_candidates(
        sheet_contexts=[_ctx("A4-02", "节点详图")],
        sheet_edges=[],
    )

    def _fake_llm_runner(payload):
        assert payload["contexts"][0]["sheet_no"] == "A4-02"
        return {
            "sheet_types": {"A4-02": "detail"},
            "linked_targets": {},
            "node_hosts": {},
        }

    graph = semantic_builder.build_sheet_graph_from_candidates(
        candidates=candidates,
        llm_runner=_fake_llm_runner,
    )

    assert graph.sheet_types["A4-02"] == "detail"
