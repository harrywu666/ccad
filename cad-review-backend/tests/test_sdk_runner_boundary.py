from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


TARGETS = [
    BACKEND_DIR / "services" / "master_planner_service.py",
    BACKEND_DIR / "services" / "audit" / "dimension_audit.py",
    BACKEND_DIR / "services" / "audit" / "relationship_discovery.py",
    BACKEND_DIR / "services" / "audit" / "index_audit.py",
    BACKEND_DIR / "services" / "audit" / "material_audit.py",
]


def test_business_agents_do_not_call_raw_kimi_functions():
    for path in TARGETS:
        content = path.read_text(encoding="utf-8")
        assert "call_kimi(" not in content, str(path)
        assert "call_kimi_stream(" not in content, str(path)

