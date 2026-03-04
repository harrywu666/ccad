"""
审核管理路由
提供审核启动、进度查询、结果查询接口
"""

from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db
from models import Project, AuditResult

router = APIRouter()


class AuditResultResponse(BaseModel):
    """审核结果响应模型"""
    id: str
    project_id: str
    audit_version: int
    type: str
    severity: str
    sheet_no_a: Optional[str] = None
    sheet_no_b: Optional[str] = None
    location: Optional[str] = None
    value_a: Optional[str] = None
    value_b: Optional[str] = None
    description: Optional[str] = None

    class Config:
        from_attributes = True


class AuditStatusResponse(BaseModel):
    """审核状态响应模型"""
    project_id: str
    status: str
    audit_version: Optional[int] = None
    current_step: Optional[str] = None
    progress: int = 0
    total_issues: int = 0


@router.get("/projects/{project_id}/audit/status", response_model=AuditStatusResponse)
def get_audit_status(project_id: str, db: Session = Depends(get_db)):
    """获取审核状态"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    latest_result = db.query(AuditResult).filter(
        AuditResult.project_id == project_id
    ).order_by(AuditResult.audit_version.desc()).first()
    
    total_issues = db.query(AuditResult).filter(
        AuditResult.project_id == project_id,
        AuditResult.audit_version == (latest_result.audit_version if latest_result else 0)
    ).count() if latest_result else 0
    
    return AuditStatusResponse(
        project_id=project_id,
        status=project.status,
        audit_version=latest_result.audit_version if latest_result else None,
        current_step=None,
        progress=100 if project.status == "done" else 0,
        total_issues=total_issues
    )


@router.get("/projects/{project_id}/audit/results", response_model=List[AuditResultResponse])
def get_audit_results(
    project_id: str, 
    version: Optional[int] = Query(None, description="审核版本号"),
    type: Optional[str] = Query(None, description="问题类型筛选"),
    db: Session = Depends(get_db)
):
    """获取审核结果"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    if not version:
        latest = db.query(AuditResult).filter(
            AuditResult.project_id == project_id
        ).order_by(AuditResult.audit_version.desc()).first()
        version = latest.audit_version if latest else 1
    
    query = db.query(AuditResult).filter(
        AuditResult.project_id == project_id,
        AuditResult.audit_version == version
    )
    
    if type:
        query = query.filter(AuditResult.type == type)
    
    return query.all()


@router.get("/projects/{project_id}/audit/history")
def get_audit_history(project_id: str, db: Session = Depends(get_db)):
    """获取审核历史记录"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    results = db.query(AuditResult).filter(
        AuditResult.project_id == project_id
    ).all()
    
    history = {}
    for result in results:
        ver = result.audit_version
        if ver not in history:
            history[ver] = {"version": ver, "count": 0, "types": {}}
        
        history[ver]["count"] += 1
        t = result.type
        if t not in history[ver]["types"]:
            history[ver]["types"][t] = 0
        history[ver]["types"][t] += 1
    
    return list(history.values())


@router.post("/projects/{project_id}/audit/start")
def start_audit(project_id: str, db: Session = Depends(get_db)):
    """开始审核"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    if project.status not in ["matching", "ready"]:
        raise HTTPException(status_code=400, detail="请先完成图纸匹配")
    
    latest = db.query(AuditResult).filter(
        AuditResult.project_id == project_id
    ).order_by(AuditResult.audit_version.desc()).first()
    
    new_version = (latest.audit_version + 1) if latest else 1
    
    old_results = db.query(AuditResult).filter(
        AuditResult.project_id == project_id
    ).all()
    for result in old_results:
        db.delete(result)
    
    project.status = "auditing"
    db.commit()
    
    return {
        "success": True, 
        "message": "审核已开始",
        "audit_version": new_version
    }


@router.post("/projects/{project_id}/audit/run")
def run_audit(project_id: str, db: Session = Depends(get_db)):
    """执行审核（三步）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    from models import JsonData
    json_list = db.query(JsonData).filter(
        JsonData.project_id == project_id,
        JsonData.is_latest == 1
    ).all()
    
    if not json_list:
        raise HTTPException(status_code=400, detail="没有可审核的数据")
    
    latest = db.query(AuditResult).filter(
        AuditResult.project_id == project_id
    ).order_by(AuditResult.audit_version.desc()).first()
    
    audit_version = (latest.audit_version + 1) if latest else 1
    
    from services.audit_service import audit_indexes, audit_dimensions, audit_materials
    
    index_issues = audit_indexes(project_id, audit_version, db)
    dimension_issues = audit_dimensions(project_id, audit_version, db)
    material_issues = audit_materials(project_id, audit_version, db)
    
    project.status = "done"
    db.commit()
    
    return {
        "success": True,
        "audit_version": audit_version,
        "total_issues": len(index_issues) + len(dimension_issues) + len(material_issues),
        "index_issues": len(index_issues),
        "dimension_issues": len(dimension_issues),
        "material_issues": len(material_issues)
    }
