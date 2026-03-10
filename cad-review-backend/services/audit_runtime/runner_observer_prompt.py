"""Runner Observer Agent 的提示资产加载器。"""

from __future__ import annotations

from pathlib import Path


_PROMPT_DIR = Path(__file__).resolve().parents[2] / "prompts" / "runner_observer"


def _read_prompt_file(name: str) -> str:
    return (_PROMPT_DIR / name).read_text(encoding="utf-8").strip()


def load_runner_observer_agent_prompt() -> str:
    return _read_prompt_file("Agent.md")


def load_runner_observer_soul_prompt() -> str:
    return _read_prompt_file("soul.md")


def build_runner_observer_system_prompt() -> str:
    agent_prompt = load_runner_observer_agent_prompt()
    soul_prompt = load_runner_observer_soul_prompt()
    return f"{agent_prompt}\n\n---\n\n{soul_prompt}".strip()


__all__ = [
    "build_runner_observer_system_prompt",
    "load_runner_observer_agent_prompt",
    "load_runner_observer_soul_prompt",
]
