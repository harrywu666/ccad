from __future__ import annotations

from pathlib import Path


FILES = [
    "/Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py",
    "/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py",
    "/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py",
    "/Users/harry/@dev/ccad/cad-review-backend/services/master_planner_service.py",
]


def test_index_material_and_core_agents_no_longer_call_kimi_directly():
    for raw_path in FILES:
        content = Path(raw_path).read_text(encoding="utf-8")
        assert "call_kimi(" not in content, raw_path
        assert "call_kimi_stream(" not in content, raw_path
