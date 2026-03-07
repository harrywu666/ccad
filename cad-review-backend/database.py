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
    - audit_results.is_resolved
    - audit_results.resolved_at
    - projects.ui_preferences
    """
    with engine.begin() as conn:
        rows = conn.execute(text("PRAGMA table_info(audit_results)")).fetchall()
        col_names = {str(row[1]) for row in rows}
        if "evidence_json" not in col_names:
            conn.execute(text("ALTER TABLE audit_results ADD COLUMN evidence_json TEXT"))
        if "is_resolved" not in col_names:
            conn.execute(text("ALTER TABLE audit_results ADD COLUMN is_resolved INTEGER DEFAULT 0"))
        if "resolved_at" not in col_names:
            conn.execute(text("ALTER TABLE audit_results ADD COLUMN resolved_at DATETIME"))

        project_rows = conn.execute(text("PRAGMA table_info(projects)")).fetchall()
        project_col_names = {str(row[1]) for row in project_rows}
        if "ui_preferences" not in project_col_names:
            conn.execute(text("ALTER TABLE projects ADD COLUMN ui_preferences TEXT"))

        drawing_rows = conn.execute(text("PRAGMA table_info(drawings)")).fetchall()
        drawing_col_names = {str(row[1]) for row in drawing_rows}
        if "annotation_board" not in drawing_col_names:
            conn.execute(text("ALTER TABLE drawings ADD COLUMN annotation_board TEXT"))

        existing_tables = {
            str(row[0])
            for row in conn.execute(
                text("SELECT name FROM sqlite_master WHERE type='table'")
            ).fetchall()
        }
        if "drawing_annotations" not in existing_tables:
            conn.execute(text("""
                CREATE TABLE drawing_annotations (
                    id TEXT PRIMARY KEY,
                    drawing_id TEXT NOT NULL REFERENCES drawings(id),
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    audit_version INTEGER NOT NULL,
                    annotation_board TEXT,
                    updated_at DATETIME,
                    UNIQUE(drawing_id, audit_version)
                )
            """))
        else:
            da_rows = conn.execute(text("PRAGMA table_info(drawing_annotations)")).fetchall()
            da_col_names = {str(row[1]) for row in da_rows}
            if "audit_version" not in da_col_names:
                conn.execute(text("DROP TABLE drawing_annotations"))
                conn.execute(text("""
                    CREATE TABLE drawing_annotations (
                        id TEXT PRIMARY KEY,
                        drawing_id TEXT NOT NULL REFERENCES drawings(id),
                        project_id TEXT NOT NULL REFERENCES projects(id),
                        audit_version INTEGER NOT NULL,
                        annotation_board TEXT,
                        updated_at DATETIME,
                        UNIQUE(drawing_id, audit_version)
                    )
                """))
