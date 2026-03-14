"""审图内核项目策略：集中管理 LLM 与并发开关。"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from typing import Any

from services.runtime_env import ensure_local_env_loaded


_DIMENSION_TRUTH_ALLOWED = {"display_value_only"}
_REPORT_SCOPE_ALLOWED = {"spaces_with_candidate_issues_only", "all_spaces"}
_AUDIENCE_ALLOWED = {"designer", "client", "supervisor"}


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "off", "no"}


def _env_int(name: str, default: int, *, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, value))


def _resolve_llm_provider() -> str:
    preferred = str(os.getenv("REVIEW_KERNEL_LLM_PROVIDER") or "").strip().lower()
    runner_mode = str(os.getenv("AUDIT_RUNNER_PROVIDER") or "").strip().lower()
    kimi_provider = str(os.getenv("KIMI_PROVIDER") or "").strip().lower()
    raw = preferred or runner_mode or kimi_provider
    if raw in {"kimi_sdk", "sdk", "codex", "codex_sdk"}:
        return "kimi_sdk"
    if raw in {"openrouter", "openrouter_api", "api", "kimi_api"}:
        return "openrouter"
    # 默认走 openrouter，避免依赖本地 SDK 才能启动
    return "openrouter"


@dataclass(slots=True)
class ProjectPolicy:
    dimension_truth_policy: str = "display_value_only"
    xref_check_enabled: bool = False
    low_confidence_gate_enabled: bool = True
    report_scope: str = "spaces_with_candidate_issues_only"
    max_concurrent_workers: int = 20
    rate_limit_retry_max: int = 5
    default_audience: str = "designer"
    llm_provider: str = "openrouter"

    @classmethod
    def from_env(cls) -> "ProjectPolicy":
        ensure_local_env_loaded()

        dimension_truth_policy = (
            str(os.getenv("REVIEW_KERNEL_DIMENSION_TRUTH_POLICY") or "display_value_only")
            .strip()
            .lower()
        )
        if dimension_truth_policy not in _DIMENSION_TRUTH_ALLOWED:
            dimension_truth_policy = "display_value_only"

        report_scope = (
            str(os.getenv("REVIEW_KERNEL_REPORT_SCOPE") or "spaces_with_candidate_issues_only")
            .strip()
            .lower()
        )
        if report_scope not in _REPORT_SCOPE_ALLOWED:
            report_scope = "spaces_with_candidate_issues_only"

        default_audience = (
            str(os.getenv("REVIEW_KERNEL_DEFAULT_AUDIENCE") or "designer")
            .strip()
            .lower()
        )
        if default_audience not in _AUDIENCE_ALLOWED:
            default_audience = "designer"

        return cls(
            dimension_truth_policy=dimension_truth_policy,
            xref_check_enabled=_env_bool("REVIEW_KERNEL_XREF_CHECK_ENABLED", False),
            low_confidence_gate_enabled=_env_bool("REVIEW_KERNEL_LOW_CONFIDENCE_GATE_ENABLED", True),
            report_scope=report_scope,
            max_concurrent_workers=_env_int(
                "REVIEW_KERNEL_MAX_CONCURRENT_WORKERS",
                20,
                minimum=1,
                maximum=64,
            ),
            rate_limit_retry_max=_env_int(
                "REVIEW_KERNEL_RATE_LIMIT_RETRY_MAX",
                5,
                minimum=1,
                maximum=20,
            ),
            default_audience=default_audience,
            llm_provider=_resolve_llm_provider(),
        )

    def to_snapshot(self) -> dict[str, Any]:
        return asdict(self)


def load_project_policy() -> ProjectPolicy:
    return ProjectPolicy.from_env()


__all__ = ["ProjectPolicy", "load_project_policy"]
