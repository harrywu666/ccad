"""
全局设置路由。
"""

from typing import List, Optional

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
from services.review_worker_skill_asset_service import (
    list_review_worker_skill_assets,
    update_review_worker_skill_assets,
)
from services.ai_prompt_service import list_prompt_stages, reset_prompt_stage, upsert_prompt_stages
from services.settings_runtime_summary_service import list_audit_runtime_summaries

router = APIRouter()


class AIPromptStageUpdate(BaseModel):
    stage_key: str
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None


class AIPromptStagesUpdatePayload(BaseModel):
    stages: List[AIPromptStageUpdate]


class FeedbackAgentPromptAssetUpdate(BaseModel):
    key: str
    content: str


class FeedbackAgentPromptAssetsUpdatePayload(BaseModel):
    items: List[FeedbackAgentPromptAssetUpdate]


class ReviewWorkerSkillAssetUpdate(BaseModel):
    key: str
    content: str


class ReviewWorkerSkillAssetsUpdatePayload(BaseModel):
    items: List[ReviewWorkerSkillAssetUpdate]


class AgentAssetUpdate(BaseModel):
    key: str
    content: str


class AgentAssetsUpdatePayload(BaseModel):
    items: List[AgentAssetUpdate]


@router.get("/settings/ai-prompts")
def get_ai_prompts(db: Session = Depends(get_db)):
    return list_prompt_stages(db)


@router.get("/settings/feedback-agent-prompts")
def get_feedback_agent_prompts():
    return list_feedback_agent_prompt_assets()


@router.get("/settings/review-worker-skills")
def get_review_worker_skill_assets():
    return list_review_worker_skill_assets()


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


@router.put("/settings/review-worker-skills")
def update_review_worker_skill_assets_detail(payload: ReviewWorkerSkillAssetsUpdatePayload):
    try:
        items = [item.model_dump() for item in payload.items]
        return update_review_worker_skill_assets(items)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/settings/ai-prompts")
def update_ai_prompts(payload: AIPromptStagesUpdatePayload, db: Session = Depends(get_db)):
    try:
        stages = [item.model_dump() for item in payload.stages]
        return upsert_prompt_stages(db, stages)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/settings/ai-prompts/{stage_key}/reset")
def reset_ai_prompt(stage_key: str, db: Session = Depends(get_db)):
    try:
        stage = reset_prompt_stage(db, stage_key)
        return {"stage": stage}
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get("/settings/audit-runtime-summaries")
def get_audit_runtime_summaries(limit: int = 10, db: Session = Depends(get_db)):
    return list_audit_runtime_summaries(db, limit=limit)
