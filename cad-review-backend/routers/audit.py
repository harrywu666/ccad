"""
审核管理路由
提供审核启动、进度查询、结果查询接口
"""

from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field, ConfigDict
from database import get_db
from models import Project, AuditResult, AuditRun, AuditTask

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
    evidence_json: Optional[str] = None

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
    run_status: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None


class AuditTaskResponse(BaseModel):
    id: str
    project_id: str
    audit_version: int
    task_type: str
    source_sheet_no: Optional[str] = None
    target_sheet_no: Optional[str] = None
    priority: int
    status: str
    trace_json: Optional[str] = None
    result_ref: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class ThreeLineSummaryResponse(BaseModel):
    total: int
    ready: int
    missing_png: int
    missing_json: int
    missing_all: int


class ThreeLineAssetResponse(BaseModel):
    id: str
    sheet_no: Optional[str] = None
    sheet_name: Optional[str] = None
    data_version: Optional[int] = None
    status: Optional[str] = None
    png_path: Optional[str] = None
    page_index: Optional[int] = None
    json_path: Optional[str] = None
    summary: Optional[str] = None
    created_at: Optional[str] = None


class ThreeLineItemResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    catalog_id: str
    sheet_no: Optional[str] = None
    sheet_name: Optional[str] = None
    sort_order: int
    status: str
    drawing: Optional[ThreeLineAssetResponse] = None
    json_data: Optional[ThreeLineAssetResponse] = Field(default=None, alias="json")


class ThreeLineMatchResponse(BaseModel):
    project_id: str
    summary: ThreeLineSummaryResponse
    items: List[ThreeLineItemResponse]


@router.get("/projects/{project_id}/audit/status", response_model=AuditStatusResponse)
def get_audit_status(project_id: str, db: Session = Depends(get_db)):
    """获取审核状态"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    from services.audit_runtime_service import get_latest_run, build_run_snapshot

    latest_run = get_latest_run(project_id, db)
    snapshot = build_run_snapshot(latest_run)

    audit_version = snapshot["audit_version"]
    if audit_version is None:
        latest_result = (
            db.query(AuditResult)
            .filter(AuditResult.project_id == project_id)
            .order_by(AuditResult.audit_version.desc())
            .first()
        )
        audit_version = latest_result.audit_version if latest_result else None

    total_issues = snapshot["total_issues"] or 0
    if audit_version is not None and total_issues == 0:
        total_issues = (
            db.query(AuditResult)
            .filter(
                AuditResult.project_id == project_id,
                AuditResult.audit_version == audit_version,
            )
            .count()
        )

    return AuditStatusResponse(
        project_id=project_id,
        status=project.status,
        audit_version=audit_version,
        current_step=snapshot["current_step"],
        progress=int(snapshot["progress"] or (100 if project.status == "done" else 0)),
        total_issues=total_issues,
        run_status=snapshot["status"],
        error=snapshot["error"],
        started_at=snapshot["started_at"],
        finished_at=snapshot["finished_at"],
    )


@router.get("/projects/{project_id}/audit/three-lines", response_model=ThreeLineMatchResponse)
def get_three_line_match(project_id: str, db: Session = Depends(get_db)):
    """获取三线匹配状态（目录/PNG/JSON）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    from services.audit_service import match_three_lines

    result = match_three_lines(project_id, db)
    return result


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

    runs = (
        db.query(AuditRun)
        .filter(AuditRun.project_id == project_id)
        .order_by(AuditRun.audit_version.desc(), AuditRun.created_at.desc())
        .all()
    )

    if runs:
        history = []
        for run in runs:
            results = (
                db.query(AuditResult)
                .filter(
                    AuditResult.project_id == project_id,
                    AuditResult.audit_version == run.audit_version,
                )
                .all()
            )
            types = {}
            for item in results:
                types[item.type] = types.get(item.type, 0) + 1

            history.append(
                {
                    "version": run.audit_version,
                    "status": run.status,
                    "current_step": run.current_step,
                    "progress": run.progress,
                    "count": run.total_issues if run.total_issues else len(results),
                    "types": types,
                    "error": run.error,
                    "started_at": run.started_at.isoformat() if run.started_at else None,
                    "finished_at": run.finished_at.isoformat() if run.finished_at else None,
                }
            )
        return history

    # 兼容旧数据：仅基于audit_results推导
    results = db.query(AuditResult).filter(AuditResult.project_id == project_id).all()
    history = {}
    for result in results:
        ver = result.audit_version
        if ver not in history:
            history[ver] = {"version": ver, "count": 0, "types": {}, "status": "done"}
        history[ver]["count"] += 1
        t = result.type
        history[ver]["types"][t] = history[ver]["types"].get(t, 0) + 1
    return list(history.values())


@router.get("/projects/{project_id}/audit/tasks", response_model=List[AuditTaskResponse])
def get_audit_tasks(
    project_id: str,
    version: Optional[int] = Query(None, description="审核版本号"),
    db: Session = Depends(get_db),
):
    """获取审核任务清单"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    if version is None:
        latest_run = (
            db.query(AuditRun)
            .filter(AuditRun.project_id == project_id)
            .order_by(AuditRun.audit_version.desc(), AuditRun.created_at.desc())
            .first()
        )
        if latest_run:
            version = latest_run.audit_version
        else:
            latest_task = (
                db.query(AuditTask)
                .filter(AuditTask.project_id == project_id)
                .order_by(AuditTask.audit_version.desc(), AuditTask.created_at.desc())
                .first()
            )
            version = latest_task.audit_version if latest_task else 1

    tasks = (
        db.query(AuditTask)
        .filter(
            AuditTask.project_id == project_id,
            AuditTask.audit_version == version,
        )
        .order_by(AuditTask.priority.asc(), AuditTask.task_type.asc(), AuditTask.created_at.asc())
        .all()
    )
    return tasks


@router.post("/projects/{project_id}/audit/tasks/plan")
def plan_audit_tasks(
    project_id: str,
    version: Optional[int] = Query(None, description="审核版本号，不传则按下一个版本规划"),
    db: Session = Depends(get_db),
):
    """手动构建图纸上下文与审核任务图"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    from services.audit_runtime_service import get_next_audit_version
    from services.context_service import build_sheet_contexts
    from services.task_planner_service import build_audit_tasks

    audit_version = version if version is not None else get_next_audit_version(project_id, db)
    context_summary = build_sheet_contexts(project_id, db)
    task_summary = build_audit_tasks(project_id, audit_version, db)
    return {
        "success": True,
        "audit_version": audit_version,
        "context_summary": context_summary,
        "task_summary": task_summary,
    }


@router.post("/projects/{project_id}/audit/start")
def start_audit(project_id: str, db: Session = Depends(get_db)):
    """开始审核"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    from services.audit_service import match_three_lines

    match_result = match_three_lines(project_id, db)
    summary = match_result["summary"]
    if summary["total"] == 0:
        raise HTTPException(status_code=400, detail="请先锁定目录")
    if summary["ready"] != summary["total"]:
        raise HTTPException(
            status_code=400,
            detail=(
                "三线匹配未完成："
                f"总数{summary['total']}，就绪{summary['ready']}，"
                f"缺PNG{summary['missing_png']}，缺JSON{summary['missing_json']}，"
                f"都缺{summary['missing_all']}"
            ),
        )
    
    from services.audit_runtime_service import (
        get_next_audit_version,
        start_audit_async,
        get_latest_run,
        is_project_running,
        mark_stale_running_runs,
    )

    if is_project_running(project_id):
        latest_run = get_latest_run(project_id, db)
        return {
            "success": True,
            "message": "审核任务已在运行",
            "audit_version": latest_run.audit_version if latest_run else None,
        }

    # 进程重启或异常中断后，清理遗留的running记录
    mark_stale_running_runs(project_id, db)

    new_version = get_next_audit_version(project_id, db)

    run = AuditRun(
        project_id=project_id,
        audit_version=new_version,
        status="running",
        current_step="等待执行",
        progress=0,
        total_issues=0,
    )
    db.add(run)
    project.status = "auditing"
    db.commit()

    try:
        start_audit_async(project_id, new_version)
    except RuntimeError as exc:
        run.status = "failed"
        run.current_step = "启动失败"
        run.error = str(exc)
        run.finished_at = datetime.now()
        project.status = "ready"
        db.commit()
        raise HTTPException(status_code=409, detail=str(exc))

    return {
        "success": True,
        "message": "审核已开始",
        "audit_version": new_version
    }


@router.post("/projects/{project_id}/audit/run")
def run_audit(project_id: str, db: Session = Depends(get_db)):
    """执行审核（三步）/查询当前执行快照（兼容旧前端）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    from services.audit_runtime_service import get_latest_run

    run = get_latest_run(project_id, db)
    if not run:
        # 兼容旧逻辑：若前端直接调用run，自动触发start
        return start_audit(project_id, db)

    response = {
        "success": True,
        "audit_version": run.audit_version,
        "status": run.status,
        "progress": run.progress,
        "current_step": run.current_step,
        "total_issues": run.total_issues,
        "error": run.error,
    }

    if run.status == "done":
        typed_counts = {}
        items = (
            db.query(AuditResult)
            .filter(
                AuditResult.project_id == project_id,
                AuditResult.audit_version == run.audit_version,
            )
            .all()
        )
        for issue in items:
            typed_counts[issue.type] = typed_counts.get(issue.type, 0) + 1
        response.update(
            {
                "index_issues": typed_counts.get("index", 0),
                "dimension_issues": typed_counts.get("dimension", 0),
                "material_issues": typed_counts.get("material", 0),
            }
        )

    return response


@router.post("/projects/{project_id}/audit/clear")
def clear_audit_report(project_id: str, db: Session = Depends(get_db)):
    """清空项目审核报告（结果、运行记录与任务记录）"""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="项目不存在")

    deleted_results = (
        db.query(AuditResult)
        .filter(AuditResult.project_id == project_id)
        .delete(synchronize_session=False)
    )
    deleted_runs = (
        db.query(AuditRun)
        .filter(AuditRun.project_id == project_id)
        .delete(synchronize_session=False)
    )
    deleted_tasks = (
        db.query(AuditTask)
        .filter(AuditTask.project_id == project_id)
        .delete(synchronize_session=False)
    )

    from services.cache_service import recalculate_project_status, increment_cache_version

    recalculate_project_status(project_id, db)
    db.commit()
    increment_cache_version(project_id, db)

    return {
        "success": True,
        "deleted": {
            "results": deleted_results,
            "runs": deleted_runs,
            "tasks": deleted_tasks,
        },
    }
