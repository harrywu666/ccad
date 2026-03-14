"""LLM 介入实现：弱辅助、候选消歧、报告表达。"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import re
from typing import Any, Awaitable, Callable

from tenacity import AsyncRetrying, retry_if_exception, stop_after_attempt, wait_exponential
from services.review_kernel.llm_boundary import (
    LLM_STAGE_DISAMBIGUATION,
    LLM_STAGE_REPORT_WRITING,
    LLM_STAGE_WEAK_ASSIST,
    check_llm_boundary,
    confidence_upper_bound_from_slice,
)
from services.review_kernel.model_gateway import InferenceRequest, ModelGateway, build_model_gateway
from services.review_kernel.policy import ProjectPolicy, load_project_policy
from services.review_kernel.prompt_assets import load_review_kernel_prompt_bundle
from services.runtime_env import ensure_local_env_loaded

LlmCall = Callable[[str, str, int], dict[str, Any] | list[dict[str, Any]]]
_CLOSE_SCORE_GAP_THRESHOLD = 0.2
_HIGH_CONFIDENCE_LOCK_THRESHOLD = 0.8
_GATEWAY_CACHE: dict[str, ModelGateway] = {}
logger = logging.getLogger(__name__)


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _stage_enabled(stage: str) -> bool:
    ensure_local_env_loaded()
    if not _env_bool("REVIEW_KERNEL_LLM_ENABLED", False):
        return False
    env_name = {
        LLM_STAGE_WEAK_ASSIST: "REVIEW_KERNEL_LLM_WEAK_ASSIST_ENABLED",
        LLM_STAGE_DISAMBIGUATION: "REVIEW_KERNEL_LLM_DISAMBIGUATION_ENABLED",
        LLM_STAGE_REPORT_WRITING: "REVIEW_KERNEL_LLM_REPORT_WRITING_ENABLED",
    }.get(stage)
    if not env_name:
        return False
    return _env_bool(env_name, True)


def _load_policy() -> ProjectPolicy:
    return load_project_policy()


def _retryable_exception(exc: BaseException) -> bool:
    text = str(exc or "").strip().lower()
    if any(token in text for token in ("429", "rate limit", "timeout", "temporarily", "unavailable")):
        return True
    return isinstance(exc, (TimeoutError, ConnectionError))


def _gateway_for_policy(policy: ProjectPolicy) -> ModelGateway:
    key = str(policy.llm_provider or "").strip().lower()
    cached = _GATEWAY_CACHE.get(key)
    if cached is not None:
        return cached
    gateway = build_model_gateway(policy)
    _GATEWAY_CACHE[key] = gateway
    return gateway


async def call_with_backoff(fn, policy: ProjectPolicy):  # noqa: ANN001
    async for attempt in AsyncRetrying(
        retry=retry_if_exception(_retryable_exception),
        wait=wait_exponential(multiplier=1, min=1, max=20),
        stop=stop_after_attempt(max(1, int(policy.rate_limit_retry_max))),
        reraise=True,
    ):
        with attempt:
            return await fn()


def get_llm_stage_switch_snapshot() -> dict[str, Any]:
    ensure_local_env_loaded()
    policy = _load_policy()
    global_enabled = _env_bool("REVIEW_KERNEL_LLM_ENABLED", False)
    return {
        "global_enabled": global_enabled,
        "provider": policy.llm_provider,
        "policy": policy.to_snapshot(),
        "weak_assist_enabled": bool(global_enabled and _stage_enabled(LLM_STAGE_WEAK_ASSIST)),
        "disambiguation_enabled": bool(global_enabled and _stage_enabled(LLM_STAGE_DISAMBIGUATION)),
        "report_writing_enabled": bool(global_enabled and _stage_enabled(LLM_STAGE_REPORT_WRITING)),
    }


def _run_async(coro: Awaitable[Any]) -> Any:
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    if not loop.is_running():
        return loop.run_until_complete(coro)

    holder: dict[str, Any] = {}

    def _runner() -> None:
        try:
            holder["result"] = asyncio.run(coro)
        except Exception as exc:  # noqa: BLE001
            holder["error"] = exc

    import threading

    t = threading.Thread(target=_runner, daemon=True)
    t.start()
    t.join()
    if "error" in holder:
        raise holder["error"]
    return holder.get("result")


def _default_llm_call(system_prompt: str, user_prompt: str, max_tokens: int) -> Any:
    policy = _load_policy()
    gateway = _gateway_for_policy(policy)
    request = InferenceRequest(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        temperature=0.0,
        max_tokens=max_tokens,
        agent_type="review_kernel",
        images=[],
    )

    async def _invoke():
        response = await gateway.multimodal_infer(request)
        return response.content

    try:
        return _run_async(call_with_backoff(_invoke, policy))
    except Exception as exc:  # noqa: BLE001
        logger.warning("review_kernel 默认 LLM 调用失败: %s", exc)
        raise


def _call_llm_json(
    *,
    system_prompt: str,
    user_prompt: str,
    max_tokens: int,
    llm_call: LlmCall | None,
) -> Any:
    caller = llm_call or _default_llm_call
    result = caller(system_prompt, user_prompt, max_tokens)
    if inspect.isawaitable(result):
        result = _run_async(result)  # pragma: no cover - 测试通常走同步路径
    return result


def _normalize_title(title: str) -> str:
    text = re.sub(r"\s+", " ", str(title or "").strip())
    return text


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _candidate_gap(candidates: list[dict[str, Any]]) -> float:
    if len(candidates) < 2:
        return 1.0
    first = _safe_float(candidates[0].get("score"), 0.0)
    second = _safe_float(candidates[1].get("score"), 0.0)
    return abs(first - second)


def _is_close_score_gap(candidates: list[dict[str, Any]]) -> bool:
    return _candidate_gap(candidates) < _CLOSE_SCORE_GAP_THRESHOLD


def _relation_is_locked_by_confidence(relation: dict[str, Any]) -> bool:
    candidates = relation.get("candidate_bindings")
    if not isinstance(candidates, list) or not candidates:
        return False
    top_score = _safe_float(candidates[0].get("score"), 0.0)
    return top_score >= _HIGH_CONFIDENCE_LOCK_THRESHOLD


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().lower()
    return text in {"1", "true", "yes", "y", "on"}


def _has_evidence(issue: dict[str, Any]) -> bool:
    evidence = issue.get("evidence")
    if isinstance(evidence, dict) and evidence:
        return True
    refs = issue.get("evidence_refs")
    return isinstance(refs, list) and bool(refs)


def _coerce_response_list(response: Any, *, candidate_keys: tuple[str, ...]) -> list[Any] | None:
    if isinstance(response, list):
        return response
    if not isinstance(response, dict):
        return None

    for key in candidate_keys:
        value = response.get(key)
        if isinstance(value, list):
            return value
    result = response.get("result")
    if isinstance(result, list):
        return result
    return None


def _build_page_classifier_system_prompt() -> str:
    bundle = load_review_kernel_prompt_bundle()
    return (
        f"{bundle.page_classifier}\n\n"
        "执行约束：你只能输出 JSON；只能做页面分类/标题归一；"
        "不要新增审图问题，不要做几何或坐标判断。"
    )


def _build_semantic_augmentor_system_prompt() -> str:
    bundle = load_review_kernel_prompt_bundle()
    return (
        f"{bundle.semantic_augmentor}\n\n"
        "执行约束：你只能从给定 candidate_id 中选择；"
        "不得发明候选，不得覆盖上游高置信结论。"
    )


def _build_review_reporter_system_prompt() -> str:
    bundle = load_review_kernel_prompt_bundle()
    return (
        f"{bundle.review_reporter}\n\n"
        "执行约束：你只能润色表达；不得改变 severity/category；"
        "不得在证据缺失时伪造完整意见。"
    )


def apply_weak_assist(
    ir_package: dict[str, Any],
    context_slice: dict[str, Any] | None,
    *,
    llm_call: LlmCall | None = None,
) -> dict[str, Any]:
    decision = check_llm_boundary(stage=LLM_STAGE_WEAK_ASSIST, context_slice=context_slice)
    semantic = ir_package.get("semantic_layer") if isinstance(ir_package.get("semantic_layer"), dict) else {}
    logical_sheets = semantic.get("logical_sheets") if isinstance(semantic.get("logical_sheets"), list) else []
    review_views = semantic.get("review_views") if isinstance(semantic.get("review_views"), list) else []
    changed = 0

    for sheet in logical_sheets:
        if not isinstance(sheet, dict):
            continue
        before = str(sheet.get("sheet_title") or "")
        after = _normalize_title(before)
        if after and after != before:
            sheet["sheet_title"] = after
            changed += 1

    for view in review_views:
        if not isinstance(view, dict):
            continue
        title_candidates = view.get("title_candidates")
        if not isinstance(title_candidates, list):
            continue
        normalized = [_normalize_title(item) for item in title_candidates]
        normalized = [item for item in normalized if item]
        if normalized and normalized != title_candidates:
            view["title_candidates"] = normalized
            changed += 1

    if not decision.allowed or not _stage_enabled(LLM_STAGE_WEAK_ASSIST):
        return {
            "llm_used": False,
            "allowed": decision.allowed,
            "reason": decision.reason,
            "changed_fields": changed,
        }

    try:
        payload = context_slice.get("payload") if isinstance(context_slice, dict) else {}
        response = _call_llm_json(
            system_prompt=_build_page_classifier_system_prompt(),
            user_prompt=json.dumps(
                {
                    "task": "classify_sheet",
                    "target_id": str((payload.get("logical_sheet") or {}).get("logical_sheet_id") or ""),
                    "logical_sheet": payload.get("logical_sheet"),
                    "review_view": payload.get("review_view"),
                    "rule_classification_result": payload.get("rule_classification_result"),
                    "layout": payload.get("layout"),
                    "output_contract": {
                        "task": "classify_sheet",
                        "target_id": "string",
                        "result": "string_or_object",
                        "confidence": 0.0,
                        "reasoning": "string",
                        "basis": ["string"],
                        "alternative": {"result": "string", "confidence": 0.0},
                        "needs_human_confirm": False,
                    },
                },
                ensure_ascii=False,
            ),
            max_tokens=600,
            llm_call=llm_call,
        )
        needs_human_confirm = False
        if isinstance(response, dict):
            title = _normalize_title(
                str(
                    response.get("sheet_title")
                    or response.get("normalized_sheet_title")
                    or (
                        response.get("result").get("sheet_title")
                        if isinstance(response.get("result"), dict)
                        else ""
                    )
                )
            )
            if title and logical_sheets and isinstance(logical_sheets[0], dict):
                logical_sheets[0]["sheet_title"] = title
                changed += 1
            needs_human_confirm = _to_bool(response.get("needs_human_confirm"))
            if needs_human_confirm and review_views and isinstance(review_views[0], dict):
                review_views[0]["needs_human_confirm"] = True
                changed += 1
        return {
            "llm_used": True,
            "allowed": True,
            "reason": "ok",
            "changed_fields": changed,
            "needs_human_confirm": needs_human_confirm,
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "llm_used": False,
            "allowed": True,
            "reason": f"llm_failed:{exc}",
            "changed_fields": changed,
        }


def _find_candidate_by_id(candidates: list[dict[str, Any]], candidate_id: str) -> dict[str, Any] | None:
    for item in candidates:
        if str(item.get("candidate_id") or "") == candidate_id:
            return item
    return None


def disambiguate_reference_bindings(
    ir_package: dict[str, Any],
    context_slice: dict[str, Any] | None,
    *,
    llm_call: LlmCall | None = None,
) -> dict[str, Any]:
    decision = check_llm_boundary(stage=LLM_STAGE_DISAMBIGUATION, context_slice=context_slice)
    semantic = ir_package.get("semantic_layer") if isinstance(ir_package.get("semantic_layer"), dict) else {}
    references = semantic.get("references") if isinstance(semantic.get("references"), list) else []
    candidate_relations = (
        semantic.get("candidate_relations")
        if isinstance(semantic.get("candidate_relations"), list)
        else []
    )
    if not references or not candidate_relations:
        return {"llm_used": False, "allowed": False, "reason": "empty_relations", "resolved_count": 0}

    relation_map = {
        str(item.get("relation_id") or ""): item
        for item in candidate_relations
        if isinstance(item, dict) and str(item.get("relation_id") or "")
    }
    selected_by_relation: dict[str, str] = {}
    human_confirm_relations: set[str] = set()
    llm_reason_by_relation: dict[str, str] = {}
    ambiguous_relations: list[dict[str, Any]] = []
    locked_count = 0
    for relation_id, relation in relation_map.items():
        candidates = relation.get("candidate_bindings")
        if not isinstance(candidates, list) or not candidates:
            continue
        top_candidate = candidates[0]
        selected_id = str(top_candidate.get("candidate_id") or "")
        if selected_id:
            selected_by_relation[relation_id] = selected_id
        if _relation_is_locked_by_confidence(relation):
            relation["llm_locked"] = True
            locked_count += 1
            continue
        needs_llm = bool(relation.get("needs_llm_disambiguation"))
        close_gap = _is_close_score_gap(candidates)
        if close_gap:
            human_confirm_relations.add(relation_id)
        if (needs_llm or close_gap) and len(candidates) > 1:
            ambiguous_relations.append(
                {
                    "relation_id": relation_id,
                    "raw_label": relation.get("raw_label"),
                    "candidates": [
                        {
                            "candidate_id": item.get("candidate_id"),
                            "sheet_no": item.get("sheet_no"),
                            "score": item.get("score"),
                            "basis": item.get("basis"),
                        }
                        for item in candidates[:6]
                    ],
                    "ambiguity_flags": relation.get("ambiguity_flags") or [],
                    "close_score_gap": round(_candidate_gap(candidates), 4),
                }
            )

    llm_used = False
    if decision.allowed and _stage_enabled(LLM_STAGE_DISAMBIGUATION) and ambiguous_relations:
        try:
            raw_response = _call_llm_json(
                system_prompt=_build_semantic_augmentor_system_prompt(),
                user_prompt=json.dumps({"relations": ambiguous_relations}, ensure_ascii=False),
                max_tokens=1200,
                llm_call=llm_call,
            )
            response = _coerce_response_list(
                raw_response,
                candidate_keys=("relations", "disambiguations", "choices", "items"),
            )
            llm_used = response is not None
            if response:
                for item in response:
                    if not isinstance(item, dict):
                        continue
                    relation_id = str(item.get("relation_id") or "")
                    candidate_id = str(item.get("candidate_id") or "")
                    relation = relation_map.get(relation_id)
                    if not relation:
                        continue
                    candidates = relation.get("candidate_bindings")
                    if not isinstance(candidates, list):
                        continue
                    if _find_candidate_by_id(candidates, candidate_id):
                        selected_by_relation[relation_id] = candidate_id
                        llm_reason_by_relation[relation_id] = str(item.get("reason") or "").strip()
                        if _to_bool(item.get("needs_human_confirm")):
                            human_confirm_relations.add(relation_id)
        except Exception:
            llm_used = False

    confidence_cap = confidence_upper_bound_from_slice(context_slice)
    resolved_count = 0
    human_confirm_count = 0
    for ref in references:
        if not isinstance(ref, dict):
            continue
        relation_id = str(ref.get("ref_id") or "")
        relation = relation_map.get(relation_id)
        if not relation:
            continue
        candidates = relation.get("candidate_bindings")
        if not isinstance(candidates, list) or not candidates:
            continue
        selected_id = selected_by_relation.get(relation_id) or str(candidates[0].get("candidate_id") or "")
        selected = _find_candidate_by_id(candidates, selected_id) or candidates[0]
        needs_human_confirm = relation_id in human_confirm_relations

        ref["selected_candidate_id"] = str(selected.get("candidate_id") or "")
        ref["target_sheet_no"] = str(selected.get("sheet_no") or "").strip() or ref.get("target_sheet_no")
        ref["target_missing"] = not bool(selected.get("is_known_sheet"))
        confidence = min(_safe_float(selected.get("score"), 0.0), confidence_cap)
        if needs_human_confirm:
            confidence = min(confidence, 0.79)
            human_confirm_count += 1
        ref["confidence"] = confidence
        ref["needs_human_confirm"] = needs_human_confirm
        ref["needs_llm_disambiguation"] = False
        relation["selected_candidate_id"] = ref["selected_candidate_id"]
        relation["confidence"] = ref["confidence"]
        relation["needs_human_confirm"] = needs_human_confirm
        reason = llm_reason_by_relation.get(relation_id)
        if reason:
            relation["disambiguation_reason"] = reason
        resolved_count += 1

    return {
        "llm_used": llm_used,
        "allowed": decision.allowed,
        "reason": decision.reason,
        "resolved_count": resolved_count,
        "ambiguous_count": len(ambiguous_relations),
        "confidence_cap": confidence_cap,
        "locked_by_confidence_count": locked_count,
        "needs_human_confirm_count": human_confirm_count,
    }


def polish_issue_writing(
    issues: list[dict[str, Any]],
    context_slice: dict[str, Any] | None,
    *,
    llm_call: LlmCall | None = None,
) -> dict[str, Any]:
    policy = _load_policy()
    decision = check_llm_boundary(stage=LLM_STAGE_REPORT_WRITING, context_slice=context_slice)
    if not decision.allowed or not _stage_enabled(LLM_STAGE_REPORT_WRITING):
        return {"llm_used": False, "allowed": decision.allowed, "reason": decision.reason, "updated": 0}

    try:
        raw_response = _call_llm_json(
            system_prompt=_build_review_reporter_system_prompt(),
            user_prompt=json.dumps(
                {
                    "audience": policy.default_audience,
                    "issues": issues[:20],
                    "output_contract": [
                        {
                            "issue_id": "string",
                            "title": "string",
                            "description": "string",
                            "suggested_fix": "string",
                            "needs_human_confirm": False,
                            "confidence": 0.0,
                        }
                    ],
                },
                ensure_ascii=False,
            ),
            max_tokens=1800,
            llm_call=llm_call,
        )
        response = _coerce_response_list(
            raw_response,
            candidate_keys=("issues", "results", "items", "rewrites"),
        )
        if not isinstance(response, list):
            return {"llm_used": False, "allowed": True, "reason": "invalid_response", "updated": 0}
        by_issue = {
            str(item.get("issue_id") or ""): item
            for item in response
            if isinstance(item, dict) and str(item.get("issue_id") or "")
        }
        updated = 0
        human_confirm_count = 0
        for issue in issues:
            issue_id = str(issue.get("issue_id") or "")
            patch = by_issue.get(issue_id)
            if not patch:
                continue
            has_evidence = _has_evidence(issue)
            for field in ("title", "description"):
                value = str(patch.get(field) or "").strip()
                if value:
                    issue[field] = value
            suggested_fix = str(patch.get("suggested_fix") or "").strip()
            if suggested_fix and has_evidence:
                issue["suggested_fix"] = suggested_fix
            needs_human_confirm = _to_bool(patch.get("needs_human_confirm")) or _to_bool(issue.get("needs_human_confirm"))
            if needs_human_confirm:
                issue["needs_human_confirm"] = True
                issue["reviewed_status"] = "suspected"
                human_confirm_count += 1
            issue["generated_by"] = "hybrid"
            updated += 1
        return {
            "llm_used": True,
            "allowed": True,
            "reason": "ok",
            "updated": updated,
            "needs_human_confirm_count": human_confirm_count,
        }
    except Exception as exc:  # noqa: BLE001
        return {"llm_used": False, "allowed": True, "reason": f"llm_failed:{exc}", "updated": 0}
