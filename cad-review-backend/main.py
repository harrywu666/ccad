"""
FastAPI 主入口文件
包含应用实例创建、CORS配置、路由注册和启动事件
"""

import logging
from importlib import import_module
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from database import init_db
from services.feedback_review_queue_service import start_feedback_review_worker, stop_feedback_review_worker
from services.runtime_env import ensure_local_env_loaded

audit = import_module("routers.audit")
catalog = import_module("routers.catalog")
categories = import_module("routers.categories")
drawings = import_module("routers.drawings")
dwg = import_module("routers.dwg")
feedback = import_module("routers.feedback")
feedback_threads = import_module("routers.feedback_threads")
projects = import_module("routers.projects")
report = import_module("routers.report")
settings = import_module("routers.settings")
skill_pack = import_module("routers.skill_pack")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
# ezdxf 的 INFO/WARNING 日志量极大（proxy object、invisible entity 等），统一静默到 ERROR
logging.getLogger("ezdxf").setLevel(logging.ERROR)
logging.getLogger("matplotlib").setLevel(logging.WARNING)


ensure_local_env_loaded()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用启动和关闭事件"""
    logger.info("正在初始化数据库...")
    init_db()
    logger.info("数据库初始化完成")
    start_feedback_review_worker(feedback_threads._process_feedback_thread_review_async)
    logger.info("误报反馈后台队列已启动")
    
    from database import SessionLocal
    from models import ProjectCategory
    
    db = SessionLocal()
    try:
        existing = db.query(ProjectCategory).first()
        if not existing:
            default_categories = [
                ProjectCategory(id="cat_1", name="住宅", color="#3B82F6", sort_order=1),
                ProjectCategory(id="cat_2", name="商业", color="#F59E0B", sort_order=2),
                ProjectCategory(id="cat_3", name="办公", color="#10B981", sort_order=3),
                ProjectCategory(id="cat_4", name="酒店", color="#8B5CF6", sort_order=4),
                ProjectCategory(id="cat_5", name="其他", color="#6B7280", sort_order=5),
            ]
            db.add_all(default_categories)
            try:
                db.commit()
                logger.info("已创建默认分类")
            except Exception:
                db.rollback()
                logger.info("默认分类已由其他进程创建，跳过")
    finally:
        db.close()
    
    yield
    stop_feedback_review_worker()
    logger.info("应用关闭")


app = FastAPI(
    title="施工图AI审核系统",
    description="室内装饰施工图AI自动审核系统后端API",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:7001", "http://127.0.0.1:7001"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(categories.router, prefix="/api", tags=["分类管理"])
app.include_router(projects.router, prefix="/api", tags=["项目管理"])
app.include_router(catalog.router, prefix="/api", tags=["目录管理"])
app.include_router(drawings.router, prefix="/api", tags=["图纸管理"])
app.include_router(dwg.router, prefix="/api", tags=["DWG管理"])
app.include_router(audit.router, prefix="/api", tags=["审核管理"])
app.include_router(report.router, prefix="/api", tags=["报告管理"])
app.include_router(settings.router, prefix="/api", tags=["系统设置"])
app.include_router(skill_pack.router, prefix="/api", tags=["审查技能包"])
app.include_router(feedback.router, prefix="/api", tags=["误报样本"])
app.include_router(feedback_threads.router, prefix="/api", tags=["误报反馈会话"])


@app.get("/")
async def root():
    """健康检查"""
    return {"status": "ok", "message": "施工图AI审核系统API运行中"}


@app.get("/api/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy", "version": "1.0.0"}
