"""运行时提示词总装配层。"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from services.ai_prompt_service import build_agent_runtime_prompt, resolve_stage_prompt_bundle
from services.audit_runtime.worker_skill_loader import load_worker_skill


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
        },
    )


def assemble_worker_runtime_prompt(
    *,
    worker_kind: str,
    task_context: dict[str, Any] | None = None,
    agent_id: str = "review_worker",
    memory_override: str | None = None,
    extra_sections: list[str] | None = None,
    user_prompt_override: str | None = None,
) -> RuntimePromptBundle:
    skill_bundle = load_worker_skill(worker_kind)
    bundle = assemble_agent_runtime_prompt(
        agent_id=agent_id,
        task_context=task_context,
        memory_override=memory_override,
        extra_sections=[skill_bundle.skill_markdown, *(extra_sections or [])],
        prompt_source="agent_skill",
        user_prompt_override=user_prompt_override,
    )
    meta = {
        **bundle.meta,
        "worker_kind": skill_bundle.worker_kind,
        "skill_id": skill_bundle.worker_kind,
        "skill_path": str(skill_bundle.skill_path),
        "skill_version": skill_bundle.skill_version,
        "runtime_scope": "chief_native_worker",
    }
    return RuntimePromptBundle(
        system_prompt=bundle.system_prompt,
        user_prompt=bundle.user_prompt,
        meta=meta,
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
    "assemble_worker_runtime_prompt",
    "render_legacy_stage_user_prompt",
]
