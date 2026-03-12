from __future__ import annotations

import sys
from pathlib import Path

import pytest


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.worker_skill_loader import load_worker_skill


def test_worker_skill_loader_reads_skill_markdown():
    bundle = load_worker_skill("index_reference")

    assert bundle.worker_kind == "index_reference"
    assert "输出必须是 JSON" in bundle.skill_markdown
    assert bundle.skill_path.name == "SKILL.md"
    assert bundle.skill_markdown.startswith("---\nname:")
    assert "description: Use when " in bundle.skill_markdown


def test_worker_skill_loader_rejects_unknown_worker_kind():
    with pytest.raises(FileNotFoundError):
        load_worker_skill("unknown_worker")


@pytest.mark.parametrize(
    ("worker_kind", "expected_name"),
    [
        ("node_host_binding", "name: node-host-binding"),
        ("index_reference", "name: index-reference"),
        ("material_semantic_consistency", "name: material-semantic-consistency"),
        ("elevation_consistency", "name: elevation-consistency"),
        ("spatial_consistency", "name: spatial-consistency"),
    ],
)
def test_worker_skill_markdown_has_callable_sections(worker_kind: str, expected_name: str):
    bundle = load_worker_skill(worker_kind)

    assert expected_name in bundle.skill_markdown
    assert "## When to Use" in bundle.skill_markdown
    assert "## Input Contract" in bundle.skill_markdown
    assert "## Output Contract" in bundle.skill_markdown
    assert "## Common Mistakes" in bundle.skill_markdown
