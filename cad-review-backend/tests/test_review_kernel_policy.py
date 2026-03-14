from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.review_kernel.policy import ProjectPolicy, load_project_policy  # noqa: E402


def test_project_policy_defaults(monkeypatch):
    monkeypatch.delenv("REVIEW_KERNEL_DIMENSION_TRUTH_POLICY", raising=False)
    monkeypatch.delenv("REVIEW_KERNEL_XREF_CHECK_ENABLED", raising=False)
    monkeypatch.delenv("REVIEW_KERNEL_LOW_CONFIDENCE_GATE_ENABLED", raising=False)
    monkeypatch.delenv("REVIEW_KERNEL_REPORT_SCOPE", raising=False)
    monkeypatch.delenv("REVIEW_KERNEL_MAX_CONCURRENT_WORKERS", raising=False)
    monkeypatch.delenv("REVIEW_KERNEL_RATE_LIMIT_RETRY_MAX", raising=False)
    monkeypatch.delenv("REVIEW_KERNEL_DEFAULT_AUDIENCE", raising=False)
    monkeypatch.delenv("REVIEW_KERNEL_LLM_PROVIDER", raising=False)
    monkeypatch.delenv("AUDIT_RUNNER_PROVIDER", raising=False)
    monkeypatch.delenv("KIMI_PROVIDER", raising=False)

    policy = load_project_policy()
    assert isinstance(policy, ProjectPolicy)
    assert policy.dimension_truth_policy == "display_value_only"
    assert policy.xref_check_enabled is False
    assert policy.low_confidence_gate_enabled is True
    assert policy.report_scope == "spaces_with_candidate_issues_only"
    assert policy.max_concurrent_workers == 20
    assert policy.rate_limit_retry_max == 5
    assert policy.default_audience == "designer"
    assert policy.llm_provider == "openrouter"


def test_project_policy_normalizes_provider_and_limits(monkeypatch):
    monkeypatch.setenv("REVIEW_KERNEL_LLM_PROVIDER", "sdk")
    monkeypatch.setenv("REVIEW_KERNEL_MAX_CONCURRENT_WORKERS", "200")
    monkeypatch.setenv("REVIEW_KERNEL_RATE_LIMIT_RETRY_MAX", "0")
    monkeypatch.setenv("REVIEW_KERNEL_DEFAULT_AUDIENCE", "CLIENT")
    monkeypatch.setenv("REVIEW_KERNEL_REPORT_SCOPE", "all_spaces")
    monkeypatch.setenv("REVIEW_KERNEL_XREF_CHECK_ENABLED", "1")

    policy = load_project_policy()
    assert policy.llm_provider == "kimi_sdk"
    assert policy.max_concurrent_workers == 64
    assert policy.rate_limit_retry_max == 1
    assert policy.default_audience == "client"
    assert policy.report_scope == "all_spaces"
    assert policy.xref_check_enabled is True
