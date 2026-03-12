"""副审 skill 注册表。"""

from __future__ import annotations

from services.audit_runtime.worker_skill_contract import WorkerSkillExecutor
from services.audit_runtime.worker_skills.dimension_consistency_skill import run_dimension_consistency_skill
from services.audit_runtime.worker_skills.index_reference_skill import run_index_reference_skill
from services.audit_runtime.worker_skills.material_semantic_skill import run_material_semantic_skill
from services.audit_runtime.worker_skills.node_host_binding_skill import run_node_host_binding_skill
from services.audit_runtime.worker_skill_loader import load_worker_skill


_CALLABLE_REGISTRY = {}


def register_worker_skill(worker_kind: str, execute) -> None:  # noqa: ANN001
    normalized = str(worker_kind or "").strip()
    if not normalized:
        raise ValueError("worker_kind_required")
    _CALLABLE_REGISTRY[normalized] = execute


register_worker_skill("index_reference", run_index_reference_skill)
register_worker_skill("material_semantic_consistency", run_material_semantic_skill)
register_worker_skill("node_host_binding", run_node_host_binding_skill)
register_worker_skill("elevation_consistency", run_dimension_consistency_skill)
register_worker_skill("spatial_consistency", run_dimension_consistency_skill)


def get_worker_skill_executor(worker_kind: str) -> WorkerSkillExecutor | None:
    normalized = str(worker_kind or "").strip()
    execute = _CALLABLE_REGISTRY.get(normalized)
    if execute is None:
        return None
    return WorkerSkillExecutor(
        worker_kind=normalized,
        skill_bundle=load_worker_skill(normalized),
        execute=execute,
    )


def has_registered_worker_skill(worker_kind: str) -> bool:
    normalized = str(worker_kind or "").strip()
    if not normalized:
        return False
    return normalized in _CALLABLE_REGISTRY


def is_skillized_worker(worker_kind: str) -> bool:
    return has_registered_worker_skill(worker_kind)


__all__ = [
    "get_worker_skill_executor",
    "has_registered_worker_skill",
    "is_skillized_worker",
    "register_worker_skill",
]
