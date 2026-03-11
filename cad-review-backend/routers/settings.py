"""
全局设置路由。
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services.feedback_agent_prompt_asset_service import (
    list_feedback_agent_prompt_assets,
    update_feedback_agent_prompt_assets,
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


@router.get("/settings/ai-prompts")
def get_ai_prompts(db: Session = Depends(get_db)):
    return list_prompt_stages(db)


@router.get("/settings/feedback-agent-prompts")
def get_feedback_agent_prompts():
    return list_feedback_agent_prompt_assets()


@router.put("/settings/feedback-agent-prompts")
def update_feedback_agent_prompts(payload: FeedbackAgentPromptAssetsUpdatePayload):
    try:
        items = [item.model_dump() for item in payload.items]
        return update_feedback_agent_prompt_assets(items)
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
