"""新架构收口后的代码扫描工具。"""

from __future__ import annotations

from pathlib import Path


_FORBIDDEN_RUNTIME_PROMPT_PATTERNS = (
    "resolve_stage_system_prompt_with_skills(",
    "resolve_stage_prompts(",
)


def scan_repo_for_runtime_legacy_stage_prompt_usage(
    repo_root: str | Path | None = None,
) -> list[str]:
    root = Path(repo_root or Path(__file__).resolve().parents[2])
    targets = [
        root / "services" / "audit",
        root / "services" / "audit_runtime",
    ]
    allowed_files = {
        root / "services" / "audit_runtime" / "runtime_prompt_assembler.py",
        root / "services" / "audit_runtime" / "cutover_scan.py",
        root / "services" / "audit" / "prompt_builder.py",
    }
    violations: list[str] = []
    for target in targets:
        for path in target.rglob("*.py"):
            if path in allowed_files:
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in _FORBIDDEN_RUNTIME_PROMPT_PATTERNS:
                if pattern in text:
                    violations.append(f"{path.relative_to(root)}::{pattern}")
    return sorted(violations)


__all__ = ["scan_repo_for_runtime_legacy_stage_prompt_usage"]
