from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services import ai_prompt_service  # noqa: E402


def test_list_prompt_stages_marks_legacy_template_compat(monkeypatch):
    monkeypatch.setattr(ai_prompt_service, "_load_override_map", lambda db: {})

    payload = ai_prompt_service.list_prompt_stages(db=None)
    stage = next(
        item for item in payload["stages"] if item["stage_key"] == "index_visual_review"
    )

    assert stage["prompt_source"] == "legacy_stage_template"
    assert stage["lifecycle"] == "legacy_template_compat"
    assert stage["runtime_scope"] == "compatibility_only"
    assert stage["compatibility_only"] is True
    assert stage["replacement"] == "review_worker/skills/index_reference/SKILL.md"
    assert stage["is_primary_runtime_source"] is False


def test_resolve_stage_prompt_bundle_keeps_legacy_meta():
    bundle = ai_prompt_service.resolve_stage_prompt_bundle(
        "material_consistency_review",
        variables={
            "sheet_no": "A1-01",
            "material_table_json": "[]",
            "material_used_json": "[]",
        },
    )

    assert bundle["meta"]["prompt_source"] == "legacy_stage_template"
    assert bundle["meta"]["lifecycle"] == "legacy_template_compat"
    assert bundle["meta"]["runtime_scope"] == "compatibility_only"
    assert bundle["meta"]["compatibility_only"] is True
    assert bundle["meta"]["is_primary_runtime_source"] is False
    assert (
        bundle["meta"]["replacement"]
        == "review_worker/skills/material_semantic_consistency/SKILL.md"
    )
    assert "A1-01" in bundle["user_prompt"]
