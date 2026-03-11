"""通用 Agent 资源读取与更新服务。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List


AGENTS_ROOT = Path(__file__).resolve().parents[1] / "agents"


@dataclass(frozen=True)
class AgentAssetDefinition:
    key: str
    file_name: str
    description: str


@dataclass(frozen=True)
class AgentAssetBundle:
    agent_markdown: str
    soul_markdown: str
    memory_markdown: str


AGENT_TITLES: dict[str, str] = {
    "chief_review": "主审 Agent",
    "runtime_guardian": "运行守护 Agent",
    "review_worker": "副审 Worker Agent",
}

ASSET_DEFINITIONS: tuple[AgentAssetDefinition, ...] = (
    AgentAssetDefinition(
        key="agent",
        file_name="AGENTS.md",
        description="这是 Agent 的硬边界，规定它能做什么、不能做什么、能调用哪些工具。",
    ),
    AgentAssetDefinition(
        key="soul",
        file_name="SOUL.md",
        description="这是 Agent 的思考气质和判断方式，决定它如何理解审图任务。",
    ),
    AgentAssetDefinition(
        key="memory",
        file_name="MEMORY.md",
        description="这是 Agent 的默认记忆模板，承载项目现场、怀疑池和经验摘要。",
    ),
)


def _definition_map() -> dict[str, AgentAssetDefinition]:
    return {item.key: item for item in ASSET_DEFINITIONS}


def _agent_dir(agent_id: str) -> Path:
    normalized = str(agent_id or "").strip()
    if normalized not in AGENT_TITLES:
        raise ValueError(f"不支持的 Agent 资源: {normalized or 'empty'}")
    return AGENTS_ROOT / normalized


def _read_asset(agent_id: str, definition: AgentAssetDefinition) -> dict:
    path = _agent_dir(agent_id) / definition.file_name
    return {
        "key": definition.key,
        "title": f"{agent_id} {definition.file_name}",
        "description": definition.description,
        "file_name": definition.file_name,
        "content": path.read_text(encoding="utf-8"),
    }


def list_agent_asset_groups() -> dict:
    return {
        "items": [
            {
                "agent_id": agent_id,
                "title": title,
            }
            for agent_id, title in AGENT_TITLES.items()
        ]
    }


def get_agent_assets(agent_id: str) -> dict:
    return {
        "agent_id": agent_id,
        "title": AGENT_TITLES[str(agent_id).strip()],
        "items": [_read_asset(agent_id, item) for item in ASSET_DEFINITIONS],
    }


def update_agent_assets(agent_id: str, items: List[dict]) -> dict:
    definition_map = _definition_map()
    seen_keys: set[str] = set()
    agent_dir = _agent_dir(agent_id)

    for item in items:
        key = str(item.get("key") or "").strip()
        if not key or key not in definition_map:
            raise ValueError(f"不支持的 Agent 资源字段: {key or 'empty'}")
        if key in seen_keys:
            raise ValueError(f"重复的 Agent 资源字段: {key}")
        content = item.get("content")
        if not isinstance(content, str):
            raise ValueError(f"{key} 的内容必须是字符串")
        normalized = content.strip()
        if not normalized:
            raise ValueError(f"{key} 不能为空")
        path = agent_dir / definition_map[key].file_name
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        seen_keys.add(key)

    return get_agent_assets(agent_id)


def load_agent_asset_bundle(agent_id: str) -> AgentAssetBundle:
    assets = get_agent_assets(agent_id)["items"]
    mapping = {item["key"]: item["content"] for item in assets}
    return AgentAssetBundle(
        agent_markdown=mapping["agent"],
        soul_markdown=mapping["soul"],
        memory_markdown=mapping["memory"],
    )


__all__ = [
    "AgentAssetBundle",
    "get_agent_assets",
    "list_agent_asset_groups",
    "load_agent_asset_bundle",
    "update_agent_assets",
]
