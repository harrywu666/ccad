"""
数据库连接模块
负责创建SQLite数据库连接和会话管理
"""

import os
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

BASE_DIR = Path.home() / "cad-review"
DB_DIR = BASE_DIR / "db"
DB_DIR.mkdir(parents=True, exist_ok=True)

DATABASE_URL = f"sqlite:///{DB_DIR / 'database.sqlite'}"

engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
    echo=False
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """获取数据库会话的依赖函数"""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """初始化数据库，创建所有表"""
    import models
    Base.metadata.create_all(bind=engine)
    _ensure_runtime_columns()


def _ensure_runtime_columns():
    """
    轻量Schema迁移（无alembic场景）：
    - audit_results.evidence_json
    - projects.ui_preferences
    """
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(audit_results)")).fetchall()
        col_names = {str(row[1]) for row in rows}
        if "evidence_json" not in col_names:
            conn.execute(text("ALTER TABLE audit_results ADD COLUMN evidence_json TEXT"))

        project_rows = conn.execute(text("PRAGMA table_info(projects)")).fetchall()
        project_col_names = {str(row[1]) for row in project_rows}
        if "ui_preferences" not in project_col_names:
            conn.execute(text("ALTER TABLE projects ADD COLUMN ui_preferences TEXT"))
