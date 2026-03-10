from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.runner_observer_prompt import (  # type: ignore[attr-defined]
    build_runner_observer_system_prompt,
)


def test_runner_observer_prompt_includes_agent_and_soul_sections():
    prompt = build_runner_observer_system_prompt()

    assert "项目级 Runner Observer Agent" in prompt
    assert "你是整轮审图的 AI 值班长" in prompt
