from __future__ import annotations

from pathlib import Path


def test_relationship_agent_no_longer_calls_kimi_directly():
    path = Path("/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py")
    content = path.read_text(encoding="utf-8")

    assert "call_kimi(" not in content
    assert "call_kimi_stream(" not in content
