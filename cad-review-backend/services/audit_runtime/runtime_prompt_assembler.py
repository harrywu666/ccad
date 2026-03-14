"""运行时提示词总装配层。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from services.ai_prompt_service import build_agent_runtime_prompt, resolve_stage_prompt_bundle


@dataclass(frozen=True)
class RuntimePromptBundle:
    system_prompt: str
    user_prompt: str
    meta: dict[str, Any]


def assemble_agent_runtime_prompt(
    *,
    agent_id: str,
    task_context: dict[str, Any] | None = None,
    memory_override: str | None = None,
    extra_sections: list[str] | None = None,
    extra_meta: dict[str, Any] | None = None,
    prompt_source: str = "agent_runtime",
    user_prompt_override: str | None = None,
) -> RuntimePromptBundle:
    system_prompt = build_agent_runtime_prompt(
        agent_id,
        memory_override=memory_override,
        extra_sections=extra_sections,
    )
    return RuntimePromptBundle(
        system_prompt=system_prompt,
        user_prompt=(
            user_prompt_override
            if isinstance(user_prompt_override, str)
            else json.dumps(task_context or {}, ensure_ascii=False, indent=2)
        ),
        meta={
            "prompt_source": prompt_source,
            "agent_id": agent_id,
            "compatibility_only": False,
            "runtime_scope": "agent_runtime",
            **dict(extra_meta or {}),
        },
    )


def assemble_legacy_stage_prompt(
    *,
    stage_key: str,
    variables: dict[str, Any] | None = None,
    user_prompt_override: str | None = None,
) -> RuntimePromptBundle:
    prompt_bundle = resolve_stage_prompt_bundle(stage_key, variables)
    return RuntimePromptBundle(
        system_prompt=str(prompt_bundle["system_prompt"]),
        user_prompt=(
            str(user_prompt_override)
            if isinstance(user_prompt_override, str)
            else str(prompt_bundle["user_prompt"])
        ),
        meta={
            **dict(prompt_bundle["meta"]),
            "runtime_scope": "compatibility_only",
            "compatibility_only": True,
        },
    )


def render_legacy_stage_user_prompt(
    *,
    stage_key: str,
    variables: dict[str, Any] | None = None,
) -> str:
    bundle = assemble_legacy_stage_prompt(stage_key=stage_key, variables=variables)
    return bundle.user_prompt


__all__ = [
    "RuntimePromptBundle",
    "assemble_agent_runtime_prompt",
    "assemble_legacy_stage_prompt",
    "render_legacy_stage_user_prompt",
]
