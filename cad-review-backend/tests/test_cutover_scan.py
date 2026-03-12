from __future__ import annotations

import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


from services.audit_runtime.cutover_scan import (  # noqa: E402
    scan_repo_for_runtime_legacy_stage_prompt_usage,
)


def test_runtime_cutover_scan_finds_no_direct_legacy_stage_prompt_usage():
    violations = scan_repo_for_runtime_legacy_stage_prompt_usage(BACKEND_DIR)

    assert violations == []
