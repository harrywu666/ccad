"""review_worker 技能文件读取与更新服务。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List


SKILLS_ROOT = Path(__file__).resolve().parents[1] / "agents" / "review_worker" / "skills"


@dataclass(frozen=True)
class ReviewWorkerSkillAssetDefinition:
    key: str
    title: str
    description: str
    skill_dir: str
    file_name: str = "SKILL.md"


SKILL_DEFINITIONS: tuple[ReviewWorkerSkillAssetDefinition, ...] = (
    ReviewWorkerSkillAssetDefinition(
        key="index_reference",
        title="索引引用 Skill",
        description="负责索引引用核查的能力说明，规定什么时候触发、输入长什么样、输出怎么交付。",
        skill_dir="index_reference",
    ),
    ReviewWorkerSkillAssetDefinition(
        key="material_semantic_consistency",
        title="材料语义一致性 Skill",
        description="负责材料语义一致性核查的能力说明，规定候选筛选、证据使用和结论格式。",
        skill_dir="material_semantic_consistency",
    ),
)


def _definition_map() -> dict[str, ReviewWorkerSkillAssetDefinition]:
    return {item.key: item for item in SKILL_DEFINITIONS}


def _skill_path(definition: ReviewWorkerSkillAssetDefinition) -> Path:
    return SKILLS_ROOT / definition.skill_dir / definition.file_name


def _read_asset(definition: ReviewWorkerSkillAssetDefinition) -> dict:
    path = _skill_path(definition)
    return {
        "key": definition.key,
        "title": definition.title,
        "description": definition.description,
        "file_name": definition.file_name,
        "content": path.read_text(encoding="utf-8"),
    }


def list_review_worker_skill_assets() -> dict:
    return {
        "items": [_read_asset(item) for item in SKILL_DEFINITIONS],
    }


def update_review_worker_skill_assets(items: List[dict]) -> dict:
    definition_map = _definition_map()
    seen_keys: set[str] = set()

    for item in items:
        key = str(item.get("key") or "").strip()
        if not key or key not in definition_map:
            raise ValueError(f"不支持的 review_worker skill 资源: {key or 'empty'}")
        if key in seen_keys:
            raise ValueError(f"重复的 review_worker skill 资源: {key}")
        content = item.get("content")
        if not isinstance(content, str):
            raise ValueError(f"{key} 的内容必须是字符串")
        if not content.strip():
            raise ValueError(f"{key} 不能为空")
        path = _skill_path(definition_map[key])
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        seen_keys.add(key)

    return list_review_worker_skill_assets()


__all__ = [
    "list_review_worker_skill_assets",
    "update_review_worker_skill_assets",
]
