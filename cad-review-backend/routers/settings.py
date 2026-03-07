"""
全局设置路由。
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services.ai_prompt_service import list_prompt_stages, reset_prompt_stage, upsert_prompt_stages

router = APIRouter()


class AIPromptStageUpdate(BaseModel):
    stage_key: str
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None


class AIPromptStagesUpdatePayload(BaseModel):
    stages: List[AIPromptStageUpdate]


@router.get("/settings/ai-prompts")
def get_ai_prompts(db: Session = Depends(get_db)):
    return list_prompt_stages(db)


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
