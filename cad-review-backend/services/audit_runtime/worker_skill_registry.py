"""副审 skill 注册表。"""

from __future__ import annotations

from importlib import import_module

from services.audit_runtime.worker_skill_contract import WorkerSkillExecutor
from services.audit_runtime.worker_skill_loader import load_worker_skill


_REGISTRY = {
    "index_reference": "services.audit_runtime.worker_skills.index_reference_skill:run_index_reference_skill",
    "material_semantic_consistency": (
        "services.audit_runtime.worker_skills.material_semantic_skill:run_material_semantic_skill"
    ),
}


def get_worker_skill_executor(worker_kind: str) -> WorkerSkillExecutor | None:
    normalized = str(worker_kind or "").strip()
    target = _REGISTRY.get(normalized)
    if not target:
        return None
    module_name, callable_name = target.split(":", 1)
    execute = getattr(import_module(module_name), callable_name)
    return WorkerSkillExecutor(
        worker_kind=normalized,
        skill_bundle=load_worker_skill(normalized),
        execute=execute,
    )


def is_skillized_worker(worker_kind: str) -> bool:
    normalized = str(worker_kind or "").strip()
    if not normalized:
        return False
    if get_worker_skill_executor(normalized) is not None:
        return True
    try:
        load_worker_skill(normalized)
    except FileNotFoundError:
        return False
    return True


__all__ = ["get_worker_skill_executor", "is_skillized_worker"]
