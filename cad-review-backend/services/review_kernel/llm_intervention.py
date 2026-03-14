"""LLM 介入实现：弱辅助、候选消歧、报告表达。"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
from typing import Any, Awaitable, Callable

from services.ai_service import call_kimi
from services.review_kernel.llm_boundary import (
    LLM_STAGE_DISAMBIGUATION,
    LLM_STAGE_REPORT_WRITING,
    LLM_STAGE_WEAK_ASSIST,
    check_llm_boundary,
    confidence_upper_bound_from_slice,
)

LlmCall = Callable[[str, str, int], dict[str, Any] | list[dict[str, Any]]]


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return str(raw).strip().lower() not in {"0", "false", "no", "off"}


def _stage_enabled(stage: str) -> bool:
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
    return _run_async(
        call_kimi(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=0.0,
            max_tokens=max_tokens,
        )
    )


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
            system_prompt=(
                "你是 CAD 图纸结构化助手。只做标题归一，不要造新字段。"
                "返回 JSON：{\"sheet_title\":\"...\"}。"
            ),
            user_prompt=json.dumps(
                {
                    "logical_sheet": payload.get("logical_sheet"),
                    "review_view": payload.get("review_view"),
                },
                ensure_ascii=False,
            ),
            max_tokens=300,
            llm_call=llm_call,
        )
        if isinstance(response, dict):
            title = _normalize_title(str(response.get("sheet_title") or ""))
            if title and logical_sheets and isinstance(logical_sheets[0], dict):
                logical_sheets[0]["sheet_title"] = title
                changed += 1
        return {
            "llm_used": True,
            "allowed": True,
            "reason": "ok",
            "changed_fields": changed,
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
    ambiguous_relations: list[dict[str, Any]] = []
    for relation_id, relation in relation_map.items():
        candidates = relation.get("candidate_bindings")
        if not isinstance(candidates, list) or not candidates:
            continue
        top_candidate = candidates[0]
        selected_id = str(top_candidate.get("candidate_id") or "")
        if selected_id:
            selected_by_relation[relation_id] = selected_id
        needs_llm = bool(relation.get("needs_llm_disambiguation"))
        if needs_llm and len(candidates) > 1:
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
                }
            )

    llm_used = False
    if decision.allowed and _stage_enabled(LLM_STAGE_DISAMBIGUATION) and ambiguous_relations:
        try:
            response = _call_llm_json(
                system_prompt=(
                    "你是 CAD 索引消歧助手。禁止创造候选。"
                    "只能从给定 candidate_id 里选。"
                    "返回 JSON 数组：[{\"relation_id\":\"...\",\"candidate_id\":\"...\",\"confidence\":0.0,\"reason\":\"...\"}]"
                ),
                user_prompt=json.dumps({"relations": ambiguous_relations}, ensure_ascii=False),
                max_tokens=900,
                llm_call=llm_call,
            )
            llm_used = True
            if isinstance(response, list):
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
        except Exception:
            llm_used = False

    confidence_cap = confidence_upper_bound_from_slice(context_slice)
    resolved_count = 0
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

        ref["selected_candidate_id"] = str(selected.get("candidate_id") or "")
        ref["target_sheet_no"] = str(selected.get("sheet_no") or "").strip() or ref.get("target_sheet_no")
        ref["target_missing"] = not bool(selected.get("is_known_sheet"))
        ref["confidence"] = min(float(selected.get("score") or 0.0), confidence_cap)
        ref["needs_llm_disambiguation"] = False
        relation["selected_candidate_id"] = ref["selected_candidate_id"]
        relation["confidence"] = ref["confidence"]
        resolved_count += 1

    return {
        "llm_used": llm_used,
        "allowed": decision.allowed,
        "reason": decision.reason,
        "resolved_count": resolved_count,
        "ambiguous_count": len(ambiguous_relations),
        "confidence_cap": confidence_cap,
    }


def polish_issue_writing(
    issues: list[dict[str, Any]],
    context_slice: dict[str, Any] | None,
    *,
    llm_call: LlmCall | None = None,
) -> dict[str, Any]:
    decision = check_llm_boundary(stage=LLM_STAGE_REPORT_WRITING, context_slice=context_slice)
    if not decision.allowed or not _stage_enabled(LLM_STAGE_REPORT_WRITING):
        return {"llm_used": False, "allowed": decision.allowed, "reason": decision.reason, "updated": 0}

    try:
        response = _call_llm_json(
            system_prompt=(
                "你是审图报告写作助手。只能润色文字，不改事实值。"
                "返回 JSON 数组：[{\"issue_id\":\"...\",\"title\":\"...\",\"description\":\"...\",\"suggested_fix\":\"...\"}]"
            ),
            user_prompt=json.dumps({"issues": issues[:20]}, ensure_ascii=False),
            max_tokens=1800,
            llm_call=llm_call,
        )
        if not isinstance(response, list):
            return {"llm_used": False, "allowed": True, "reason": "invalid_response", "updated": 0}
        by_issue = {
            str(item.get("issue_id") or ""): item
            for item in response
            if isinstance(item, dict) and str(item.get("issue_id") or "")
        }
        updated = 0
        for issue in issues:
            issue_id = str(issue.get("issue_id") or "")
            patch = by_issue.get(issue_id)
            if not patch:
                continue
            for field in ("title", "description", "suggested_fix"):
                value = str(patch.get(field) or "").strip()
                if value:
                    issue[field] = value
            issue["generated_by"] = "hybrid"
            updated += 1
        return {"llm_used": True, "allowed": True, "reason": "ok", "updated": updated}
    except Exception as exc:  # noqa: BLE001
        return {"llm_used": False, "allowed": True, "reason": f"llm_failed:{exc}", "updated": 0}
