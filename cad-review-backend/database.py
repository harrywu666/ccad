"""
数据库连接模块
负责创建SQLite数据库连接和会话管理
"""

import os
from pathlib import Path
from sqlalchemy import create_engine, text
from sqlalchemy.orm import close_all_sessions, sessionmaker, declarative_base

BASE_DIR = Path.home() / "cad-review"
DB_DIR = BASE_DIR / "db"
DB_DIR.mkdir(parents=True, exist_ok=True)

DB_PATH_OVERRIDE = os.getenv("CCAD_DB_PATH", "").strip()
if DB_PATH_OVERRIDE:
    database_path = Path(DB_PATH_OVERRIDE).expanduser()
    database_path.parent.mkdir(parents=True, exist_ok=True)
else:
    database_path = DB_DIR / "database.sqlite"

DATABASE_URL = f"sqlite:///{database_path}"

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


def dispose_db_engine() -> None:
    """释放当前进程内的会话与数据库连接。"""
    close_all_sessions()
    engine.dispose()


def _ensure_runtime_columns():
    """
    轻量Schema迁移（无alembic场景）：
    - audit_results.evidence_json
    - audit_results.is_resolved
    - audit_results.resolved_at
    - audit_results.feedback_status
    - audit_results.feedback_at
    - audit_results.rule_id / finding_type / finding_status / source_agent / evidence_pack_id / review_round / triggered_by / confidence
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
        if "feedback_status" not in col_names:
            conn.execute(text("ALTER TABLE audit_results ADD COLUMN feedback_status TEXT DEFAULT 'none'"))
        if "feedback_at" not in col_names:
            conn.execute(text("ALTER TABLE audit_results ADD COLUMN feedback_at DATETIME"))
        if "feedback_note" not in col_names:
            conn.execute(text("ALTER TABLE audit_results ADD COLUMN feedback_note TEXT"))
        if "rule_id" not in col_names:
            conn.execute(text("ALTER TABLE audit_results ADD COLUMN rule_id TEXT"))
        if "finding_type" not in col_names:
            conn.execute(text("ALTER TABLE audit_results ADD COLUMN finding_type TEXT"))
        if "finding_status" not in col_names:
            conn.execute(text("ALTER TABLE audit_results ADD COLUMN finding_status TEXT"))
        if "source_agent" not in col_names:
            conn.execute(text("ALTER TABLE audit_results ADD COLUMN source_agent TEXT"))
        if "evidence_pack_id" not in col_names:
            conn.execute(text("ALTER TABLE audit_results ADD COLUMN evidence_pack_id TEXT"))
        if "review_round" not in col_names:
            conn.execute(text("ALTER TABLE audit_results ADD COLUMN review_round INTEGER DEFAULT 1"))
        if "triggered_by" not in col_names:
            conn.execute(text("ALTER TABLE audit_results ADD COLUMN triggered_by TEXT"))
        if "confidence" not in col_names:
            conn.execute(text("ALTER TABLE audit_results ADD COLUMN confidence REAL"))

        project_rows = conn.execute(text("PRAGMA table_info(projects)")).fetchall()
        project_col_names = {str(row[1]) for row in project_rows}
        if "ui_preferences" not in project_col_names:
            conn.execute(text("ALTER TABLE projects ADD COLUMN ui_preferences TEXT"))

        drawing_rows = conn.execute(text("PRAGMA table_info(drawings)")).fetchall()
        drawing_col_names = {str(row[1]) for row in drawing_rows}
        if "annotation_board" not in drawing_col_names:
            conn.execute(text("ALTER TABLE drawings ADD COLUMN annotation_board TEXT"))

        audit_run_rows = conn.execute(text("PRAGMA table_info(audit_runs)")).fetchall()
        audit_run_col_names = {str(row[1]) for row in audit_run_rows}
        if "provider_mode" not in audit_run_col_names:
            conn.execute(text("ALTER TABLE audit_runs ADD COLUMN provider_mode TEXT"))

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

        if "feedback_samples" not in existing_tables:
            conn.execute(text("""
                CREATE TABLE feedback_samples (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    audit_result_id TEXT NOT NULL,
                    audit_version INTEGER NOT NULL,
                    issue_type TEXT NOT NULL,
                    severity TEXT,
                    sheet_no_a TEXT,
                    sheet_no_b TEXT,
                    location TEXT,
                    description TEXT,
                    evidence_json TEXT,
                    value_a TEXT,
                    value_b TEXT,
                    user_note TEXT,
                    snapshot_json TEXT,
                    curation_status TEXT DEFAULT 'new',
                    created_at DATETIME,
                    curated_at DATETIME
                )
            """))

        if "audit_issue_drawings" not in existing_tables:
            conn.execute(text("""
                CREATE TABLE audit_issue_drawings (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    audit_result_id TEXT NOT NULL REFERENCES audit_results(id),
                    audit_version INTEGER NOT NULL,
                    match_side TEXT NOT NULL,
                    drawing_id TEXT REFERENCES drawings(id),
                    drawing_data_version INTEGER,
                    sheet_no TEXT,
                    sheet_name TEXT,
                    index_no TEXT,
                    anchor_json TEXT,
                    match_status TEXT DEFAULT 'matched',
                    created_at DATETIME,
                    updated_at DATETIME,
                    UNIQUE(audit_result_id, match_side)
                )
            """))

        if "drawing_layout_registrations" not in existing_tables:
            conn.execute(text("""
                CREATE TABLE drawing_layout_registrations (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    drawing_id TEXT NOT NULL REFERENCES drawings(id),
                    drawing_data_version INTEGER,
                    sheet_no TEXT,
                    layout_name TEXT NOT NULL,
                    pdf_page_index INTEGER,
                    layout_page_range_json TEXT,
                    pdf_page_size_json TEXT,
                    transform_json TEXT,
                    registration_method TEXT DEFAULT 'layout_page_direct',
                    registration_confidence REAL DEFAULT 1.0,
                    created_at DATETIME,
                    updated_at DATETIME,
                    UNIQUE(drawing_id, layout_name, pdf_page_index)
                )
            """))

        if "audit_run_events" not in existing_tables:
            conn.execute(text("""
                CREATE TABLE audit_run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id TEXT NOT NULL REFERENCES projects(id),
                    audit_version INTEGER NOT NULL,
                    level TEXT DEFAULT 'info',
                    step_key TEXT,
                    agent_key TEXT,
                    agent_name TEXT,
                    event_kind TEXT,
                    progress_hint INTEGER,
                    message TEXT NOT NULL,
                    meta_json TEXT,
                    created_at DATETIME
                )
            """))
        else:
            audit_event_rows = conn.execute(text("PRAGMA table_info(audit_run_events)")).fetchall()
            audit_event_col_names = {str(row[1]) for row in audit_event_rows}
            if "agent_key" not in audit_event_col_names:
                conn.execute(text("ALTER TABLE audit_run_events ADD COLUMN agent_key TEXT"))
            if "agent_name" not in audit_event_col_names:
                conn.execute(text("ALTER TABLE audit_run_events ADD COLUMN agent_name TEXT"))
            if "event_kind" not in audit_event_col_names:
                conn.execute(text("ALTER TABLE audit_run_events ADD COLUMN event_kind TEXT"))
            if "progress_hint" not in audit_event_col_names:
                conn.execute(text("ALTER TABLE audit_run_events ADD COLUMN progress_hint INTEGER"))
