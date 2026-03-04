"""
缓存版本服务模块
提供项目缓存版本号管理功能
"""

from datetime import datetime
from sqlalchemy.orm import Session
from models import Project, Catalog, Drawing, JsonData


def increment_cache_version(project_id: str, db: Session) -> int:
    """
    增加项目缓存版本号
    
    Args:
        project_id: 项目ID
        db: 数据库会话
    
    Returns:
        新的缓存版本号
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if project:
        project.cache_version += 1
        project.updated_at = datetime.now()
        db.commit()
        return project.cache_version
    return 0


def check_cache_version(project_id: str, client_version: int, db: Session) -> dict:
    """
    检查缓存版本是否需要刷新
    
    Args:
        project_id: 项目ID
        client_version: 客户端缓存版本
        db: 数据库会话
    
    Returns:
        包含needs_refresh和server_version的字典
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return {"needs_refresh": True, "server_version": 0}
    
    return {
        "needs_refresh": project.cache_version > client_version,
        "server_version": project.cache_version
    }


def recalculate_project_status(project_id: str, db: Session) -> str:
    """
    按三线匹配情况重算项目状态：
    - 无锁定目录：new
    - 有锁定目录但尚未上传图纸/DWG：catalog_locked
    - 锁定目录未全部形成三线匹配：matching
    - 锁定目录全部形成三线匹配：ready
    """
    db.flush()
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        return ""

    locked_catalogs = db.query(Catalog).filter(
        Catalog.project_id == project_id,
        Catalog.status == "locked"
    ).all()

    if not locked_catalogs:
        project.status = "new"
        return project.status

    locked_catalog_ids = {item.id for item in locked_catalogs}

    drawing_rows = db.query(Drawing.catalog_id).filter(
        Drawing.project_id == project_id,
        Drawing.replaced_at == None
    ).all()
    has_drawings = len(drawing_rows) > 0
    drawing_catalog_ids = {row[0] for row in drawing_rows if row[0]}

    json_rows = db.query(JsonData.catalog_id).filter(
        JsonData.project_id == project_id,
        JsonData.is_latest == 1
    ).all()
    has_json_data = len(json_rows) > 0
    json_catalog_ids = {row[0] for row in json_rows if row[0]}

    if not has_drawings and not has_json_data:
        project.status = "catalog_locked"
    elif locked_catalog_ids.issubset(drawing_catalog_ids) and locked_catalog_ids.issubset(json_catalog_ids):
        project.status = "ready"
    else:
        project.status = "matching"

    return project.status
