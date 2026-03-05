"""
项目文件存储路径服务
新项目落盘到仓库根目录的 `projecs/项目名`，同时兼容旧版 `~/cad-review/projects/{project_id}`。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

MARKER_FILENAME = ".project_id"
WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
PROJECTS_ROOT = WORKSPACE_ROOT / "projecs"
LEGACY_PROJECTS_ROOT = Path.home() / "cad-review" / "projects"


def _sanitize_project_name(name: str) -> str:
    text = (name or "").strip()
    if not text:
        return "未命名项目"
    text = re.sub(r"[\\/:\*\?\"<>\|]+", "_", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text or "未命名项目"


def _marker_path(project_dir: Path) -> Path:
    return project_dir / MARKER_FILENAME


def _read_marker(project_dir: Path) -> str:
    try:
        marker = _marker_path(project_dir)
        if not marker.exists():
            return ""
        return marker.read_text(encoding="utf-8").strip()
    except Exception:
        return ""


def _write_marker(project_dir: Path, project_id: str) -> None:
    marker = _marker_path(project_dir)
    marker.write_text(project_id, encoding="utf-8")


def _find_by_marker(project_id: str) -> Optional[Path]:
    if not PROJECTS_ROOT.exists():
        return None
    for child in PROJECTS_ROOT.iterdir():
        if not child.is_dir():
            continue
        if _read_marker(child) == project_id:
            return child
    return None


def _preferred_dir(project_name: str, project_id: str) -> Path:
    base_name = _sanitize_project_name(project_name)
    primary = PROJECTS_ROOT / base_name

    if not primary.exists():
        return primary

    marker_value = _read_marker(primary)
    if marker_value in {"", project_id}:
        return primary

    return PROJECTS_ROOT / f"{base_name}__{project_id[-8:]}"


def resolve_project_dir(project, *, ensure: bool = False) -> Path:  # noqa: ANN001
    """
    解析项目目录路径：
    1) 优先找新路径里带 marker 的目录（按 project_id 精确匹配）
    2) 兼容旧路径 ~/cad-review/projects/{project_id}
    3) 都没有时，返回新路径候选目录（按项目名）
    """
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)

    by_marker = _find_by_marker(project.id)
    if by_marker:
        if ensure:
            by_marker.mkdir(parents=True, exist_ok=True)
            _write_marker(by_marker, project.id)
        return by_marker

    legacy = LEGACY_PROJECTS_ROOT / project.id
    if legacy.exists():
        return legacy

    preferred = _preferred_dir(getattr(project, "name", ""), project.id)
    if ensure:
        preferred.mkdir(parents=True, exist_ok=True)
        _write_marker(preferred, project.id)
    return preferred


def ensure_project_scaffold(project_dir: Path) -> None:
    for name in ("catalog", "pngs", "jsons", "reports", "dwg", "cache"):
        (project_dir / name).mkdir(parents=True, exist_ok=True)


def remove_project_dirs(project) -> None:  # noqa: ANN001
    """
    删除项目目录（新路径与旧路径都尝试清理）。
    """
    import shutil

    candidates = []
    current = resolve_project_dir(project, ensure=False)
    candidates.append(current)
    candidates.append(LEGACY_PROJECTS_ROOT / project.id)

    seen = set()
    for path in candidates:
        if not path:
            continue
        key = str(path.resolve()) if path.exists() else str(path)
        if key in seen:
            continue
        seen.add(key)
        if path.exists():
            shutil.rmtree(path)


def rename_project_named_dir(project, old_name: str, new_name: str) -> None:  # noqa: ANN001
    """
    项目改名时，若当前使用的是新路径（projecs）目录，则同步重命名目录。
    旧路径（legacy）不做迁移，避免破坏已有绝对路径记录。
    """
    if not new_name or old_name == new_name:
        return

    current = resolve_project_dir(project, ensure=False)
    try:
        in_new_root = current.resolve().parent == PROJECTS_ROOT.resolve()
    except Exception:
        in_new_root = False
    if not in_new_root or not current.exists():
        return

    target = _preferred_dir(new_name, project.id)
    if target == current:
        return
    if target.exists():
        # 已有目标目录时只补marker，不强行覆盖
        _write_marker(target, project.id)
        return

    current.rename(target)
    _write_marker(target, project.id)


def _rewrite_path_prefix(path_value: Optional[str], old_root: Path, new_root: Path) -> Optional[str]:
    if not path_value:
        return path_value
    raw = str(path_value)
    old_raw = str(old_root)
    old_resolved = str(old_root.resolve())

    source = raw
    rel = None
    if source.startswith(old_raw):
        rel = source[len(old_raw):].lstrip("/\\")
    elif source.startswith(old_resolved):
        rel = source[len(old_resolved):].lstrip("/\\")
    else:
        try:
            rel = str(Path(source).resolve().relative_to(old_root.resolve()))
        except Exception:
            rel = None

    if rel is None:
        return path_value
    return str(new_root / rel)


def migrate_legacy_project(project, db, *, dry_run: bool = False) -> dict:  # noqa: ANN001
    """
    迁移单个旧项目目录：
    ~/cad-review/projects/{project_id} -> {workspace}/projecs/{project_name}
    并修正数据库内的绝对路径字段。
    """
    from models import Drawing, JsonData, SheetContext

    legacy_dir = LEGACY_PROJECTS_ROOT / project.id
    if not legacy_dir.exists():
        return {
            "project_id": project.id,
            "project_name": project.name,
            "migrated": False,
            "reason": "legacy_not_found",
        }

    target_dir = _preferred_dir(getattr(project, "name", ""), project.id)
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)

    if dry_run:
        return {
            "project_id": project.id,
            "project_name": project.name,
            "legacy_dir": str(legacy_dir),
            "target_dir": str(target_dir),
            "migrated": False,
            "reason": "dry_run",
        }

    import shutil

    if target_dir.exists():
        marker = _read_marker(target_dir)
        if marker not in {"", project.id}:
            return {
                "project_id": project.id,
                "project_name": project.name,
                "legacy_dir": str(legacy_dir),
                "target_dir": str(target_dir),
                "migrated": False,
                "reason": f"target_conflict:{marker}",
            }
        # 目标已存在且可用：合并旧目录内容（极少见）
        for child in legacy_dir.iterdir():
            dest = target_dir / child.name
            if dest.exists():
                continue
            shutil.move(str(child), str(dest))
        shutil.rmtree(legacy_dir)
    else:
        shutil.move(str(legacy_dir), str(target_dir))

    _write_marker(target_dir, project.id)
    ensure_project_scaffold(target_dir)

    drawing_count = 0
    for row in db.query(Drawing).filter(Drawing.project_id == project.id).all():
        new_path = _rewrite_path_prefix(row.png_path, legacy_dir, target_dir)
        if new_path != row.png_path:
            row.png_path = new_path
            drawing_count += 1

    json_count = 0
    for row in db.query(JsonData).filter(JsonData.project_id == project.id).all():
        new_path = _rewrite_path_prefix(row.json_path, legacy_dir, target_dir)
        if new_path != row.json_path:
            row.json_path = new_path
            json_count += 1

    context_count = 0
    meta_count = 0
    contexts = db.query(SheetContext).filter(SheetContext.project_id == project.id).all()
    for row in contexts:
        changed = False
        new_l2_json = _rewrite_path_prefix(row.layer_l2_json_path, legacy_dir, target_dir)
        if new_l2_json != row.layer_l2_json_path:
            row.layer_l2_json_path = new_l2_json
            changed = True

        new_l2_pdf = _rewrite_path_prefix(row.layer_l2_pdf_path, legacy_dir, target_dir)
        if new_l2_pdf != row.layer_l2_pdf_path:
            row.layer_l2_pdf_path = new_l2_pdf
            changed = True

        if changed:
            context_count += 1

        if row.meta_json:
            try:
                meta_obj = json.loads(row.meta_json)
            except Exception:
                meta_obj = None
            if isinstance(meta_obj, dict):
                png_path = _rewrite_path_prefix(meta_obj.get("png_path"), legacy_dir, target_dir)
                json_path = _rewrite_path_prefix(meta_obj.get("json_path"), legacy_dir, target_dir)
                if png_path != meta_obj.get("png_path") or json_path != meta_obj.get("json_path"):
                    meta_obj["png_path"] = png_path
                    meta_obj["json_path"] = json_path
                    row.meta_json = json.dumps(meta_obj, ensure_ascii=False)
                    meta_count += 1

    db.commit()

    return {
        "project_id": project.id,
        "project_name": project.name,
        "legacy_dir": str(legacy_dir),
        "target_dir": str(target_dir),
        "migrated": True,
        "drawing_paths_updated": drawing_count,
        "json_paths_updated": json_count,
        "context_paths_updated": context_count,
        "context_meta_updated": meta_count,
    }
