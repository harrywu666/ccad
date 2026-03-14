"""review_kernel 资产读取与更新服务。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List


AGENTS_ROOT = Path(__file__).resolve().parents[1] / "agents" / "review_kernel"


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
    "review_kernel": "审图内核资产",
}

ASSET_DEFINITIONS: tuple[AgentAssetDefinition, ...] = (
    AgentAssetDefinition(
        key="soul_core",
        file_name="SOUL.md",
        description="内核共用 SOUL，统一价值观和边界。",
    ),
    AgentAssetDefinition(
        key="page_classifier_agent",
        file_name="AGENT_PageClassifier.md",
        description="页面分类代理规则。",
    ),
    AgentAssetDefinition(
        key="page_classifier_soul_delta",
        file_name="SOUL_DELTA_PageClassifier.md",
        description="页面分类代理的 SOUL 增量约束。",
    ),
    AgentAssetDefinition(
        key="semantic_augmentor_agent",
        file_name="AGENT_SemanticAugmentor.md",
        description="语义增强代理规则。",
    ),
    AgentAssetDefinition(
        key="semantic_augmentor_soul_delta",
        file_name="SOUL_DELTA_SemanticAugmentor.md",
        description="语义增强代理的 SOUL 增量约束。",
    ),
    AgentAssetDefinition(
        key="review_reporter_agent",
        file_name="AGENT_ReviewReporter.md",
        description="审图结论整理代理规则。",
    ),
    AgentAssetDefinition(
        key="review_reporter_soul_delta",
        file_name="SOUL_DELTA_ReviewReporter.md",
        description="审图结论整理代理的 SOUL 增量约束。",
    ),
    AgentAssetDefinition(
        key="review_qa_agent",
        file_name="AGENT_ReviewQA.md",
        description="审图问答代理规则。",
    ),
    AgentAssetDefinition(
        key="review_qa_soul_delta",
        file_name="SOUL_DELTA_ReviewQA.md",
        description="审图问答代理的 SOUL 增量约束。",
    ),
)


def _definition_map() -> dict[str, AgentAssetDefinition]:
    return {item.key: item for item in ASSET_DEFINITIONS}


def _agent_dir(agent_id: str) -> Path:
    normalized = str(agent_id or "").strip()
    if normalized not in AGENT_TITLES:
        raise ValueError(f"不支持的 Agent 资源: {normalized or 'empty'}")
    return AGENTS_ROOT


def _read_asset(agent_id: str, definition: AgentAssetDefinition) -> dict:
    path = _agent_dir(agent_id) / definition.file_name
    return {
        "key": definition.key,
        "title": definition.file_name,
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
    if str(agent_id or "").strip() != "review_kernel":
        raise ValueError(f"不支持的 Agent 资源: {agent_id or 'empty'}")
    assets = get_agent_assets("review_kernel")["items"]
    mapping = {str(item["file_name"]).strip(): item["content"] for item in assets}
    return AgentAssetBundle(
        agent_markdown=mapping.get("AGENT_ReviewReporter.md", ""),
        soul_markdown=mapping.get("SOUL.md", ""),
        memory_markdown="",
    )


__all__ = [
    "AgentAssetBundle",
    "get_agent_assets",
    "list_agent_asset_groups",
    "load_agent_asset_bundle",
    "update_agent_assets",
]
