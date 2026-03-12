"""主审怀疑卡规划器。"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
import re
from typing import Any

from domain.sheet_normalization import normalize_sheet_no
from services.agent_asset_service import AgentAssetBundle, load_agent_asset_bundle
from services.audit_runtime.runtime_prompt_assembler import (
    RuntimePromptBundle,
    assemble_agent_runtime_prompt,
)


@dataclass(frozen=True)
class ChiefReviewPlannerResult:
    items: list[dict[str, Any]]
    prompt_bundle: RuntimePromptBundle
    meta: dict[str, Any]
    chief_recheck_queue: list[dict[str, Any]] = field(default_factory=list)


_SECTION_PATTERN_TEMPLATE = r"^##\s+{heading}\s*$([\s\S]*?)(?=^##\s+|\Z)"


@dataclass(frozen=True)
class ChiefPlannerRule:
    target_types: tuple[str, ...]
    worker_kind: str
    topic: str
    review_focus: str
    suspect_reason: str
    priority: float
    objective_template: str


@dataclass(frozen=True)
class ChiefPlannerPolicy:
    rules: tuple[ChiefPlannerRule, ...]
    chief_recheck_min_priority: float
    escalated_active_min_priority: float
    required_memory_slots: tuple[str, ...]


def _build_planner_payload(
    *,
    project_id: str,
    audit_version: int,
    memory: dict[str, Any] | None,
    sheet_graph,
) -> dict[str, Any]:  # noqa: ANN001
    memory = dict(memory or {})
    return {
        "project_id": project_id,
        "audit_version": audit_version,
        "memory": {
            "confirmed_links": list(memory.get("confirmed_links") or []),
            "false_positive_hints": list(memory.get("false_positive_hints") or []),
            "resolved_hypotheses": list(memory.get("resolved_hypotheses") or []),
            "active_hypotheses": list(memory.get("active_hypotheses") or []),
        },
        "sheet_graph": {
            "sheet_types": dict(getattr(sheet_graph, "sheet_types", {}) or {}),
            "linked_targets": dict(getattr(sheet_graph, "linked_targets", {}) or {}),
        },
    }


def _extract_section(markdown: str, heading: str) -> str:
    pattern = re.compile(
        _SECTION_PATTERN_TEMPLATE.format(heading=re.escape(heading)),
        re.MULTILINE,
    )
    match = pattern.search(markdown or "")
    return (match.group(1) if match else "").strip()


def _parse_rule_line(line: str) -> dict[str, str]:
    payload: dict[str, str] = {}
    for segment in [item.strip() for item in line.split("|") if item.strip()]:
        if "=" not in segment:
            continue
        key, value = segment.split("=", 1)
        payload[key.strip()] = value.strip()
    return payload


def _parse_float_rule(value: str, *, field_name: str) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError) as exc:
        raise ValueError(f"chief_review_rule_invalid:{field_name}") from exc


def _load_chief_planner_policy() -> ChiefPlannerPolicy:
    bundle: AgentAssetBundle = load_agent_asset_bundle("chief_review")
    mapping_section = _extract_section(bundle.agent_markdown, "主审任务映射")
    if not mapping_section:
        raise ValueError("chief_review_rules_missing")

    rules: list[ChiefPlannerRule] = []
    for raw_line in mapping_section.splitlines():
        line = raw_line.strip()
        if not line.startswith("- "):
            continue
        payload = _parse_rule_line(line[2:])
        if not payload:
            continue
        target_types_raw = str(payload.get("target_types") or "").strip()
        worker_kind = str(payload.get("worker_kind") or "").strip()
        topic = str(payload.get("topic") or "").strip()
        review_focus = str(payload.get("focus") or "").strip()
        suspect_reason = str(payload.get("suspect_reason") or "").strip()
        objective_template = str(payload.get("objective") or "").strip()
        if not all(
            [
                target_types_raw,
                worker_kind,
                topic,
                review_focus,
                suspect_reason,
                objective_template,
            ]
        ):
            raise ValueError("chief_review_rule_incomplete")
        target_types = tuple(
            sorted(
                {
                    item.strip().lower()
                    for item in target_types_raw.split(",")
                    if item.strip()
                }
            )
        )
        if not target_types:
            raise ValueError("chief_review_rule_target_types_missing")
        rules.append(
            ChiefPlannerRule(
                target_types=target_types,
                worker_kind=worker_kind,
                topic=topic,
                review_focus=review_focus,
                suspect_reason=suspect_reason,
                priority=_parse_float_rule(payload.get("priority"), field_name="priority"),
                objective_template=objective_template,
            )
        )
    if not rules:
        raise ValueError("chief_review_rules_empty")

    priority_section = _extract_section(bundle.agent_markdown, "主审优先级规则")
    priority_rules = {
        key: value
        for raw_line in priority_section.splitlines()
        if (line := raw_line.strip()).startswith("- ")
        for key, value in [((line[2:].split("=", 1) + [""])[:2])]
        if str(key).strip()
    }

    memory_section = _extract_section(bundle.memory_markdown, "必备记忆槽")
    required_memory_slots = tuple(
        item.strip()
        for raw_line in memory_section.splitlines()
        if (item := raw_line.strip().removeprefix("-").strip())
    )
    if not required_memory_slots:
        raise ValueError("chief_review_memory_slots_missing")

    return ChiefPlannerPolicy(
        rules=tuple(rules),
        chief_recheck_min_priority=_parse_float_rule(
            priority_rules.get("chief_recheck_min_priority", "0.99"),
            field_name="chief_recheck_min_priority",
        ),
        escalated_active_min_priority=_parse_float_rule(
            priority_rules.get("escalated_active_min_priority", "0.98"),
            field_name="escalated_active_min_priority",
        ),
        required_memory_slots=required_memory_slots,
    )


def _normalized_scope_key(
    source_sheet_no: str,
    target_sheet_nos: list[str],
    worker_kind: str,
) -> tuple[str, tuple[str, ...], str]:
    return (
        normalize_sheet_no(source_sheet_no),
        tuple(
            sorted(
                {
                    normalize_sheet_no(item)
                    for item in list(target_sheet_nos or [])
                    if normalize_sheet_no(item)
                }
            )
        ),
        str(worker_kind or "").strip(),
    )


def _memory_scope_key(item: dict[str, Any]) -> tuple[str, tuple[str, ...], str]:
    context = dict(item.get("context") or {})
    return _normalized_scope_key(
        str(item.get("source_sheet_no") or "").strip(),
        [str(target).strip() for target in list(item.get("target_sheet_nos") or []) if str(target).strip()],
        str(item.get("worker_kind") or context.get("suggested_worker_kind") or "").strip(),
    )


def _match_rule_for_target_type(
    target_type: str,
    *,
    policy: ChiefPlannerPolicy,
) -> ChiefPlannerRule:
    normalized = str(target_type or "").strip().lower()
    for rule in policy.rules:
        if "*" in rule.target_types or normalized in rule.target_types:
            return rule
    raise ValueError(f"chief_review_rule_not_found:{normalized or 'unknown'}")


def _build_hypothesis_blueprint(
    rule: ChiefPlannerRule,
    *,
    source_sheet_no: str,
    target_sheet_nos: list[str],
    target_types: list[str],
) -> tuple[str, str, float, dict[str, Any]]:
    target_label = ", ".join(target_sheet_nos[:3])
    return (
        rule.topic,
        rule.objective_template.format(
            source_sheet_no=source_sheet_no,
            target_label=target_label,
        ),
        rule.priority,
        {
            "review_focus": rule.review_focus,
            "suspect_reason": rule.suspect_reason,
            "suggested_worker_kind": rule.worker_kind,
            "target_sheet_types": target_types,
        },
    )


def _merge_recheck_queue(
    policy: ChiefPlannerPolicy,
    existing_active: dict[tuple[str, tuple[str, ...], str], dict[str, Any]],
    chief_recheck_queue: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[str, tuple[str, ...], str]] = set()
    for item in list(chief_recheck_queue or []):
        scope_key = _memory_scope_key(dict(item or {}))
        if not scope_key[0] or not scope_key[1] or not scope_key[2] or scope_key in seen:
            continue
        existing = existing_active.get(scope_key)
        payload = dict(existing or item or {})
        context = dict(payload.get("context") or {})
        context["needs_chief_review"] = True
        context.setdefault("suggested_worker_kind", scope_key[2])
        payload["context"] = context
        payload["priority"] = max(float(payload.get("priority") or 0.5), policy.chief_recheck_min_priority)
        payload["worker_kind"] = scope_key[2]
        merged.append(payload)
        seen.add(scope_key)
    return merged


def build_default_chief_hypotheses(
    *,
    sheet_graph,
    memory: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:  # noqa: ANN001
    memory = dict(memory or {})
    policy = _load_chief_planner_policy()
    for required_slot in policy.required_memory_slots:
        memory.setdefault(required_slot, [])
    existing_active = {
        _memory_scope_key(dict(item or {})): dict(item or {})
        for item in list(memory.get("active_hypotheses") or [])
        if _memory_scope_key(dict(item or {}))[0]
    }
    skip_keys = {
        _memory_scope_key(dict(item or {}))
        for item in [
            *list(memory.get("false_positive_hints") or []),
            *list(memory.get("resolved_hypotheses") or []),
        ]
        if _memory_scope_key(dict(item or {}))[0]
    }
    chief_recheck_queue = _merge_recheck_queue(
        policy,
        existing_active,
        list(memory.get("chief_recheck_queue") or []),
    )

    worker_order = {
        rule.worker_kind: index
        for index, rule in enumerate(policy.rules)
    }
    hypotheses: list[dict[str, Any]] = []
    used_existing_keys: set[tuple[str, tuple[str, ...], str]] = set()
    hypothesis_index = 1

    linked_targets = dict(getattr(sheet_graph, "linked_targets", {}) or {})
    sheet_types = dict(getattr(sheet_graph, "sheet_types", {}) or {})
    confirmed_links = list(memory.get("confirmed_links") or [])
    if not linked_targets and confirmed_links:
        for item in confirmed_links:
            source = str(item.get("source_sheet_no") or "").strip()
            targets = [str(target).strip() for target in list(item.get("target_sheet_nos") or []) if str(target).strip()]
            if source and targets:
                linked_targets[source] = targets

    for source_sheet_no, raw_targets in sorted(linked_targets.items()):
        grouped_targets: dict[str, list[str]] = defaultdict(list)
        for target_sheet_no in list(raw_targets or []):
            target = str(target_sheet_no or "").strip()
            if not target:
                continue
            matched_rule = _match_rule_for_target_type(
                str(sheet_types.get(target, "unknown") or "unknown"),
                policy=policy,
            )
            worker_kind = matched_rule.worker_kind
            if target not in grouped_targets[worker_kind]:
                grouped_targets[worker_kind].append(target)

        for worker_kind, targets in sorted(grouped_targets.items(), key=lambda item: worker_order.get(item[0], 99)):
            scope_key = _normalized_scope_key(source_sheet_no, targets, worker_kind)
            if not scope_key[0] or not scope_key[1] or scope_key in skip_keys:
                continue
            existing = existing_active.get(scope_key)
            target_types = [
                str(sheet_types.get(item, "unknown") or "unknown").strip()
                for item in targets
            ]
            matched_rule = _match_rule_for_target_type(
                target_types[0] if target_types else "unknown",
                policy=policy,
            )
            topic, objective, priority, context = _build_hypothesis_blueprint(
                matched_rule,
                source_sheet_no=source_sheet_no,
                target_sheet_nos=targets,
                target_types=target_types,
            )
            if existing:
                used_existing_keys.add(scope_key)
                existing_context = dict(existing.get("context") or {})
                context = {
                    **context,
                    **existing_context,
                    "suggested_worker_kind": matched_rule.worker_kind,
                }
                if existing_context.get("needs_chief_review"):
                    priority = max(
                        priority,
                        float(existing.get("priority") or 0.5),
                        policy.escalated_active_min_priority,
                    )
            hypotheses.append(
                {
                    "id": str((existing or {}).get("id") or f"hyp-{hypothesis_index}").strip() or f"hyp-{hypothesis_index}",
                    "topic": str((existing or {}).get("topic") or topic).strip() or topic,
                    "objective": str((existing or {}).get("objective") or objective).strip() or objective,
                    "source_sheet_no": source_sheet_no,
                    "target_sheet_nos": list(targets),
                    "priority": priority,
                    "context": context,
                    "worker_kind": worker_kind,
                }
            )
            hypothesis_index += 1

    for scope_key, existing in existing_active.items():
        if scope_key in used_existing_keys:
            continue
        context = dict(existing.get("context") or {})
        if not context.get("needs_chief_review"):
            continue
        hypotheses.append(
            {
                **existing,
                "priority": max(
                    float(existing.get("priority") or 0.5),
                    policy.escalated_active_min_priority,
                ),
                "worker_kind": scope_key[2],
                "context": {
                    **context,
                    "needs_chief_review": True,
                    "suggested_worker_kind": scope_key[2],
                },
            }
        )

    return hypotheses, chief_recheck_queue


def plan_chief_review_hypotheses(
    *,
    project_id: str,
    audit_version: int,
    memory: dict[str, Any] | None,
    sheet_graph,
) -> ChiefReviewPlannerResult:  # noqa: ANN001
    policy = _load_chief_planner_policy()
    prompt_bundle = assemble_agent_runtime_prompt(
        agent_id="chief_review",
        task_context=_build_planner_payload(
            project_id=project_id,
            audit_version=audit_version,
            memory=memory,
            sheet_graph=sheet_graph,
        ),
        prompt_source="chief_agent",
    )
    items, chief_recheck_queue = build_default_chief_hypotheses(
        sheet_graph=sheet_graph,
        memory=memory,
    )
    return ChiefReviewPlannerResult(
        items=items,
        prompt_bundle=prompt_bundle,
        chief_recheck_queue=chief_recheck_queue,
        meta={
            **prompt_bundle.meta,
            "planner_mode": "chief_resource_planner",
            "planner_source": "chief_agent",
            "hypothesis_count": len(items),
            "chief_recheck_count": len(chief_recheck_queue),
            "planner_rules_source": "chief_review_assets",
            "planner_rule_count": len(policy.rules),
        },
    )


__all__ = [
    "ChiefReviewPlannerResult",
    "build_default_chief_hypotheses",
    "plan_chief_review_hypotheses",
]
