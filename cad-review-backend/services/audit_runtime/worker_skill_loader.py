"""副审 skill 资源加载。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import hashlib
from pathlib import Path


SKILLS_ROOT = Path(__file__).resolve().parents[2] / "agents" / "review_worker" / "skills"


@dataclass(frozen=True)
class WorkerSkillBundle:
    worker_kind: str
    skill_markdown: str
    skill_path: Path
    skill_version: str


@lru_cache(maxsize=16)
def load_worker_skill(worker_kind: str) -> WorkerSkillBundle:
    normalized = str(worker_kind or "").strip()
    skill_path = (SKILLS_ROOT / normalized / "SKILL.md").resolve()
    if not skill_path.exists():
        raise FileNotFoundError(normalized)
    skill_markdown = skill_path.read_text(encoding="utf-8")
    return WorkerSkillBundle(
        worker_kind=normalized,
        skill_markdown=skill_markdown,
        skill_path=skill_path,
        skill_version=hashlib.sha1(skill_markdown.encode("utf-8")).hexdigest()[:12],
    )


__all__ = ["SKILLS_ROOT", "WorkerSkillBundle", "load_worker_skill"]
