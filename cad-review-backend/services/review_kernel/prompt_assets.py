"""review_kernel 的 AGENT/SOUL 提示词资产装载。"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


PROMPT_ROOT = Path(__file__).resolve().parents[2] / "agents" / "review_kernel"

_FALLBACK_SOUL = (
    "你是证据驱动的施工图语义代理。"
    "不得编造候选，不得掩盖不确定性，不得脱离结构化证据做强结论。"
)
_FALLBACK_PAGE_CLASSIFIER = (
    "你是 PageClassifier。只做图纸分类和标题归一，不做几何判断，不输出审图问题。"
)
_FALLBACK_SEMANTIC_AUGMENTOR = (
    "你是 SemanticAugmentor。只在给定候选集内做排序与裁决，不得发明目标。"
)
_FALLBACK_REVIEW_REPORTER = (
    "你是 ReviewReporter。只润色表达，不改变问题严重级别，不补造证据。"
)
_FALLBACK_REVIEW_QA = (
    "你是 ReviewQA。只回答当前项目可验证事实，不用通用知识填空。"
)


@dataclass(frozen=True)
class ReviewKernelPromptBundle:
    page_classifier: str
    semantic_augmentor: str
    review_reporter: str
    review_qa: str


def _read_prompt_file(file_name: str, fallback: str) -> str:
    path = PROMPT_ROOT / file_name
    if not path.exists():
        return fallback
    try:
        text = path.read_text(encoding="utf-8").strip()
    except Exception:
        return fallback
    return text or fallback


def _join_prompt_parts(*parts: str) -> str:
    items = [str(item or "").strip() for item in parts if str(item or "").strip()]
    return "\n\n---\n\n".join(items)


@lru_cache(maxsize=1)
def load_review_kernel_prompt_bundle() -> ReviewKernelPromptBundle:
    soul = _read_prompt_file("SOUL.md", _FALLBACK_SOUL)
    page_classifier = _join_prompt_parts(
        soul,
        _read_prompt_file("SOUL_DELTA_PageClassifier.md", ""),
        _read_prompt_file("AGENT_PageClassifier.md", _FALLBACK_PAGE_CLASSIFIER),
    )
    semantic_augmentor = _join_prompt_parts(
        soul,
        _read_prompt_file("SOUL_DELTA_SemanticAugmentor.md", ""),
        _read_prompt_file("AGENT_SemanticAugmentor.md", _FALLBACK_SEMANTIC_AUGMENTOR),
    )
    review_reporter = _join_prompt_parts(
        soul,
        _read_prompt_file("SOUL_DELTA_ReviewReporter.md", ""),
        _read_prompt_file("AGENT_ReviewReporter.md", _FALLBACK_REVIEW_REPORTER),
    )
    review_qa = _join_prompt_parts(
        soul,
        _read_prompt_file("SOUL_DELTA_ReviewQA.md", ""),
        _read_prompt_file("AGENT_ReviewQA.md", _FALLBACK_REVIEW_QA),
    )
    return ReviewKernelPromptBundle(
        page_classifier=page_classifier,
        semantic_augmentor=semantic_augmentor,
        review_reporter=review_reporter,
        review_qa=review_qa,
    )


__all__ = ["ReviewKernelPromptBundle", "load_review_kernel_prompt_bundle"]
