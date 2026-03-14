"""
全局设置路由。
"""

from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services.agent_asset_service import (
    get_agent_assets,
    list_agent_asset_groups,
    update_agent_assets,
)
from services.feedback_agent_prompt_asset_service import (
    list_feedback_agent_prompt_assets,
    update_feedback_agent_prompt_assets,
)
from services.settings_runtime_summary_service import list_audit_runtime_summaries

router = APIRouter()


class FeedbackAgentPromptAssetUpdate(BaseModel):
    key: str
    content: str


class FeedbackAgentPromptAssetsUpdatePayload(BaseModel):
    items: List[FeedbackAgentPromptAssetUpdate]


class AgentAssetUpdate(BaseModel):
    key: str
    content: str


class AgentAssetsUpdatePayload(BaseModel):
    items: List[AgentAssetUpdate]


@router.get("/settings/feedback-agent-prompts")
def get_feedback_agent_prompts():
    return list_feedback_agent_prompt_assets()


@router.get("/settings/agent-assets")
def get_agent_asset_groups():
    return list_agent_asset_groups()


@router.get("/settings/agent-assets/{agent_id}")
def get_agent_assets_detail(agent_id: str):
    try:
        return get_agent_assets(agent_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/settings/agent-assets/{agent_id}")
def update_agent_assets_detail(agent_id: str, payload: AgentAssetsUpdatePayload):
    try:
        items = [item.model_dump() for item in payload.items]
        return update_agent_assets(agent_id, items)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/settings/feedback-agent-prompts")
def update_feedback_agent_prompts(payload: FeedbackAgentPromptAssetsUpdatePayload):
    try:
        items = [item.model_dump() for item in payload.items]
        return update_feedback_agent_prompt_assets(items)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/settings/audit-runtime-summaries")
def get_audit_runtime_summaries(limit: int = 10, db: Session = Depends(get_db)):
    return list_audit_runtime_summaries(db, limit=limit)
