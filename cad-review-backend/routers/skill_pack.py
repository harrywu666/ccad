"""审查技能包设置路由。"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from services.skill_pack_service import (
    create_skill_entry,
    delete_skill_entry,
    generate_rules,
    list_skill_entries,
    list_skill_types,
    toggle_skill_entry,
    update_skill_entry,
)

router = APIRouter()


class SkillPackCreatePayload(BaseModel):
    skill_type: str
    title: str
    content: str
    priority: int = 100
    stage_keys: Optional[List[str]] = None


class SkillPackUpdatePayload(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    priority: Optional[int] = None
    stage_keys: Optional[List[str]] = None


class SkillPackTogglePayload(BaseModel):
    is_active: bool


class SkillPackGeneratePayload(BaseModel):
    skill_type: str


@router.get("/settings/skill-types")
def get_skill_types():
    return list_skill_types()


@router.get("/settings/skill-packs")
def get_skill_packs(skill_type: Optional[str] = None, db: Session = Depends(get_db)):
    try:
        return list_skill_entries(db, skill_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/settings/skill-packs")
def create_skill_pack(payload: SkillPackCreatePayload, db: Session = Depends(get_db)):
    try:
        return create_skill_entry(
            db,
            skill_type=payload.skill_type,
            title=payload.title,
            content=payload.content,
            priority=payload.priority,
            stage_keys=payload.stage_keys,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/settings/skill-packs/{entry_id}")
def update_skill_pack(entry_id: str, payload: SkillPackUpdatePayload, db: Session = Depends(get_db)):
    try:
        return update_skill_entry(
            db,
            entry_id,
            title=payload.title,
            content=payload.content,
            priority=payload.priority,
            stage_keys=payload.stage_keys,
        )
    except ValueError as exc:
        status_code = 404 if str(exc) == "skill_entry_not_found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc))


@router.delete("/settings/skill-packs/{entry_id}")
def remove_skill_pack(entry_id: str, db: Session = Depends(get_db)):
    try:
        return delete_skill_entry(db, entry_id)
    except ValueError as exc:
        status_code = 404 if str(exc) == "skill_entry_not_found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc))


@router.post("/settings/skill-packs/{entry_id}/toggle")
def change_skill_pack_status(
    entry_id: str,
    payload: SkillPackTogglePayload,
    db: Session = Depends(get_db),
):
    try:
        return toggle_skill_entry(db, entry_id, payload.is_active)
    except ValueError as exc:
        status_code = 404 if str(exc) == "skill_entry_not_found" else 400
        raise HTTPException(status_code=status_code, detail=str(exc))


@router.post("/settings/skill-packs/generate")
def generate_skill_packs(payload: SkillPackGeneratePayload, db: Session = Depends(get_db)):
    try:
        return generate_rules(db, payload.skill_type)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
