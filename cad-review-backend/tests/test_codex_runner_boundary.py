from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def test_business_agents_do_not_call_codex_bridge_directly():
    from services.audit_runtime.providers import codex_sdk_provider

    direct_calls: list[str] = []
    for relative_path in (
        "services/master_planner_service.py",
        "services/audit/dimension_audit.py",
        "services/audit/index_audit.py",
        "services/audit/material_audit.py",
        "services/audit/relationship_discovery.py",
    ):
        content = (BACKEND_DIR / relative_path).read_text(encoding="utf-8")
        if "codex_bridge_client" in content or "CODEX_BRIDGE_BASE_URL" in content:
            direct_calls.append(relative_path)

    assert getattr(codex_sdk_provider, "CODEX_BRIDGE_BOUNDARY", False) is True
    assert not direct_calls
