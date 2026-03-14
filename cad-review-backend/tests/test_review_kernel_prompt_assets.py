from __future__ import annotations

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.review_kernel.prompt_assets import load_review_kernel_prompt_bundle  # noqa: E402


def test_review_kernel_prompt_assets_loaded_from_repo_docs():
    bundle = load_review_kernel_prompt_bundle()
    assert "What I Am" in bundle.page_classifier
    assert "PageClassifier" in bundle.page_classifier
    assert "SemanticAugmentor" in bundle.semantic_augmentor
    assert "ReviewReporter" in bundle.review_reporter
    assert "ReviewQA" in bundle.review_qa
