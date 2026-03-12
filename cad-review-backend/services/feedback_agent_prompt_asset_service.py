"""误报反馈 Agent 提示资产设置服务。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List


PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts" / "feedback_agent"


@dataclass(frozen=True)
class FeedbackAgentPromptAssetDefinition:
    key: str
    title: str
    description: str
    file_name: str


ASSET_DEFINITIONS: tuple[FeedbackAgentPromptAssetDefinition, ...] = (
    FeedbackAgentPromptAssetDefinition(
        key="prompt",
        title="误报反馈 PROMPT.md",
        description="这是误报反馈 Agent 的用户任务模板文件，决定它看到的约束、字段格式和上下文结构。",
        file_name="PROMPT.md",
    ),
    FeedbackAgentPromptAssetDefinition(
        key="agent",
        title="误报反馈 AGENT.md",
        description="这是误报反馈 Agent 的角色说明文件，决定它该做什么、不该做什么。",
        file_name="AGENT.md",
    ),
    FeedbackAgentPromptAssetDefinition(
        key="soul",
        title="误报反馈 SOUL.md",
        description="这是误报反馈 Agent 的气质和判断原则文件，决定它回答时的风格和底线。",
        file_name="SOUL.md",
    ),
)


def _definition_map() -> dict[str, FeedbackAgentPromptAssetDefinition]:
    return {item.key: item for item in ASSET_DEFINITIONS}


def _read_asset(definition: FeedbackAgentPromptAssetDefinition) -> dict:
    path = PROMPT_DIR / definition.file_name
    return {
        "key": definition.key,
        "title": definition.title,
        "description": definition.description,
        "file_name": definition.file_name,
        "content": path.read_text(encoding="utf-8"),
    }


def list_feedback_agent_prompt_assets() -> dict:
    return {
        "items": [_read_asset(item) for item in ASSET_DEFINITIONS],
    }


def update_feedback_agent_prompt_assets(items: List[dict]) -> dict:
    definition_map = _definition_map()
    seen_keys: set[str] = set()

    for item in items:
        key = str(item.get("key") or "").strip()
        if not key or key not in definition_map:
            raise ValueError(f"不支持的误报反馈提示资产: {key or 'empty'}")
        if key in seen_keys:
            raise ValueError(f"重复的误报反馈提示资产: {key}")
        content = item.get("content")
        if not isinstance(content, str):
            raise ValueError(f"{key} 的内容必须是字符串")
        normalized = content.strip()
        if not normalized:
            raise ValueError(f"{key} 不能为空")
        path = PROMPT_DIR / definition_map[key].file_name
        path.write_text(content.rstrip() + "\n", encoding="utf-8")
        seen_keys.add(key)

    return list_feedback_agent_prompt_assets()


__all__ = [
    "list_feedback_agent_prompt_assets",
    "update_feedback_agent_prompt_assets",
]
