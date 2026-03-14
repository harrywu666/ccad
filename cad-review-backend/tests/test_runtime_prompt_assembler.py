from __future__ import annotations

import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.runtime_prompt_assembler import (  # noqa: E402
    assemble_agent_runtime_prompt,
    assemble_legacy_stage_prompt,
)


def test_assemble_agent_runtime_prompt_uses_runtime_scope():
    bundle = assemble_agent_runtime_prompt(
        agent_id="review_kernel",
        task_context={"source_sheet_no": "A1-01", "target_sheet_nos": ["A4-01"]},
    )

    assert bundle.meta["prompt_source"] == "agent_runtime"
    assert bundle.meta["agent_id"] == "review_kernel"
    assert bundle.meta["compatibility_only"] is False
    assert bundle.meta["runtime_scope"] == "agent_runtime"
    assert "replacement" not in bundle.meta
    assert "stage_key" not in bundle.meta
    assert json.loads(bundle.user_prompt)["source_sheet_no"] == "A1-01"


def test_assemble_legacy_stage_prompt_marks_template_source():
    bundle = assemble_legacy_stage_prompt(
        stage_key="index_visual_review",
        variables={
            "source_sheet_no": "A1-01",
            "target_sheet_no": "A4-01",
            "index_no": "D1",
            "issue_kind": "missing_reverse_link",
            "issue_description": "目标图未找到反向索引",
        },
    )

    assert bundle.meta["prompt_source"] == "legacy_stage_template"
    assert bundle.meta["stage_key"] == "index_visual_review"
    assert bundle.meta["compatibility_only"] is True
    assert bundle.meta["runtime_scope"] == "compatibility_only"
    assert "索引复核专家" in bundle.system_prompt
    assert "A1-01" in bundle.user_prompt
