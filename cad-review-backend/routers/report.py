"""
报告管理路由
提供PDF和Excel格式的审核报告下载接口
"""

from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from database import get_db
from models import Project, AuditResult

router = APIRouter()

BASE_DIR = Path.home() / "cad-review"


@router.get("/projects/{project_id}/report/pdf")
def generate_pdf_report(project_id: str, version: Optional[int] = None, db: Session = Depends(get_db)):
    """生成并下载PDF报告"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    if not version:
        latest = db.query(AuditResult).filter(
            AuditResult.project_id == project_id
        ).order_by(AuditResult.audit_version.desc()).first()
        version = latest.audit_version if latest else 1
    
    results = db.query(AuditResult).filter(
        AuditResult.project_id == project_id,
        AuditResult.audit_version == version
    ).all()
    
    from services.report_service import generate_pdf
    pdf_path = generate_pdf(project, results, version)
    
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=f"{project.name}_审核报告_v{version}.pdf"
    )


@router.get("/projects/{project_id}/report/excel")
def generate_excel_report(project_id: str, version: Optional[int] = None, db: Session = Depends(get_db)):
    """生成并下载Excel报告"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")
    
    if not version:
        latest = db.query(AuditResult).filter(
            AuditResult.project_id == project_id
        ).order_by(AuditResult.audit_version.desc()).first()
        version = latest.audit_version if latest else 1
    
    results = db.query(AuditResult).filter(
        AuditResult.project_id == project_id,
        AuditResult.audit_version == version
    ).all()
    
    from services.report_service import generate_excel
    excel_path = generate_excel(project, results, version)
    
    return FileResponse(
        excel_path,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        filename=f"{project.name}_审核报告_v{version}.xlsx"
    )
