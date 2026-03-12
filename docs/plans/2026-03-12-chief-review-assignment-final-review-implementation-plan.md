# Chief Review Assignment + Final Review Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild the chief-review runtime around incremental assignment dispatch, one visible worker card per assignment, explicit final review, Markdown-first reporting, and grounding-preserving structured conversion.

**Architecture:** Keep the existing `chief_review` runtime shell, event bus, worker skill library, and report pipeline, but replace the current `hypothesis -> low-level session fan-out -> direct finding synthesis` path with `ReviewAssignment -> single worker session per assignment -> Final Review Agent -> Organizer Agent -> FinalIssue converter`. Grounding becomes a gate in the final-review stage rather than an optional report-time enhancement.

**Tech Stack:** Python, FastAPI, SQLAlchemy, pytest, React, Vite, Vitest, existing audit runtime event stream, existing report generation stack

---

### Execution Order

Implement tasks in numeric order.

- Task 2 depends on Task 1 because `ChiefReviewSession.plan_assignments(...)` must emit `ReviewAssignment`, and the schema from Task 1 defines the valid target-count and grounding-related contract boundaries.
- Task 3 depends on Task 2 because visible worker identity only makes sense after assignment-scoped dispatch exists.
- Task 5 depends on Tasks 2-4 because final review must consume assignment-scoped worker conclusions plus evidence bundles.
- Task 6 depends on Task 5 because organizer output and `FinalIssue` conversion only apply to final-review accepted results.
- Tasks 7-9 should execute after Tasks 1-6 are green, otherwise frontend state and report verification will target unstable runtime contracts.

### Task 1: Introduce assignment-first runtime schema and hard constraints

**Files:**
- Modify: `cad-review-backend/services/audit_runtime/review_task_schema.py`
- Create: `cad-review-backend/services/audit_runtime/final_review_schema.py`
- Test: `cad-review-backend/tests/test_review_task_schema.py`
- Test: `cad-review-backend/tests/test_final_review_schema.py`

**Step 1: Write the failing tests**

```python
def test_review_assignment_rejects_more_than_two_targets():
    with pytest.raises(ValidationError):
        ReviewAssignment(
            assignment_id="a1",
            review_intent="elevation_consistency",
            source_sheet_no="A1.06",
            target_sheet_nos=["A2.00", "A2.01", "A2.02"],
            task_title="A1.06 -> A2.*",
            acceptance_criteria=["..."],
            expected_evidence_types=["anchors"],
            priority=0.9,
            dispatch_reason="chief_dispatch",
        )
```

```python
def test_final_issue_requires_grounded_anchors():
    with pytest.raises(ValidationError):
        FinalIssue(
            issue_code="ISS-001",
            title="标高不一致",
            description="...",
            severity="warning",
            finding_type="dim_mismatch",
            disposition="accepted",
            source_agent="organizer_agent",
            source_assignment_id="a1",
            source_sheet_no="A1.06",
            target_sheet_nos=["A2.00"],
            location_text="入口立面附近",
            evidence_pack_id="pack-1",
            anchors=[],
            confidence=0.91,
            review_round=1,
            organizer_markdown_block="## 问题 1",
        )
```

**Step 2: Run tests to verify they fail**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_review_task_schema.py tests/test_final_review_schema.py -q`

Expected: FAIL because `ReviewAssignment`, `FinalIssue`, and grounding validation do not exist yet.

**Step 3: Implement the minimal schema layer**

```python
class ReviewAssignment(BaseModel):
    assignment_id: str
    review_intent: str
    source_sheet_no: str
    target_sheet_nos: list[str]
    ...

    @field_validator("target_sheet_nos")
    @classmethod
    def _validate_targets(cls, value: list[str]) -> list[str]:
        if not value or len(value) > 2:
            raise ValueError("target_sheet_nos must contain 1-2 sheets")
        return value
```

```python
class FinalIssue(BaseModel):
    ...
    anchors: list[AnchorPayload]

    @model_validator(mode="after")
    def _validate_grounding(self) -> "FinalIssue":
        if not self.anchors:
            raise ValueError("FinalIssue requires grounded anchors")
        return self
```

**Step 4: Run tests to verify they pass**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_review_task_schema.py tests/test_final_review_schema.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add cad-review-backend/services/audit_runtime/review_task_schema.py cad-review-backend/services/audit_runtime/final_review_schema.py cad-review-backend/tests/test_review_task_schema.py cad-review-backend/tests/test_final_review_schema.py
git commit -m "feat: add assignment and final review schemas"
```

### Task 2: Replace hypothesis planning with incremental assignment dispatch

**Files:**
- Modify: `cad-review-backend/services/audit_runtime/chief_review_session.py`
- Modify: `cad-review-backend/services/audit_runtime/orchestrator.py`
- Modify: `cad-review-backend/services/chief_review_memory_service.py`
- Create: `cad-review-backend/services/audit_runtime/chief_dispatch_policy.py`
- Test: `cad-review-backend/tests/test_chief_review_session.py`
- Test: `cad-review-backend/tests/test_chief_review_orchestrator.py`
- Test: `cad-review-backend/tests/test_chief_dispatch_policy.py`

**Step 1: Write the failing tests**

```python
def test_chief_review_session_splits_multi_target_hypothesis_into_small_assignments():
    session = ChiefReviewSession(project_id="p1", audit_version=7)
    assignments = session.plan_assignments(memory={
        "active_hypotheses": [{
            "id": "hyp-1",
            "topic": "标高一致性",
            "objective": "核对 A1.06 与 A2.00, A2.01, A2.02 的标高一致性",
            "source_sheet_no": "A1.06",
            "target_sheet_nos": ["A2.00", "A2.01", "A2.02"],
        }]
    })
    assert [item.target_sheet_nos for item in assignments] == [["A2.00"], ["A2.01"], ["A2.02"]]
```

```python
def test_dispatch_policy_stops_when_no_workers_pending_no_final_review_pending_and_no_new_directions():
    decision = evaluate_dispatch_state(...)
    assert decision.should_stop is True
```

```python
def test_orchestrator_dispatches_incrementally_instead_of_single_bulk_batch(monkeypatch):
    captured = []
    ...
    assert captured == ["assignment-1", "assignment-2", "assignment-3"]
```

**Step 2: Run tests to verify they fail**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_chief_review_session.py tests/test_chief_review_orchestrator.py tests/test_chief_dispatch_policy.py -q`

Expected: FAIL because planning is still `active_hypotheses -> worker_tasks` in one bulk step.

**Step 3: Implement minimal incremental dispatch**

```python
class DispatchDecision(BaseModel):
    should_dispatch: bool
    should_wait: bool
    should_stop: bool
    reason: str
```

```python
def plan_assignments(self, memory: dict[str, Any]) -> list[ReviewAssignment]:
    assignments: list[ReviewAssignment] = []
    for hypothesis in active_hypotheses:
        assignments.extend(_split_hypothesis_into_assignments(hypothesis))
    return assignments
```

```python
while True:
    decision = evaluate_dispatch_state(...)
    if decision.should_stop:
        break
    if decision.should_wait:
        continue
    next_assignment = chief_session.next_assignment(...)
    ...
```

**Step 4: Run tests to verify they pass**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_chief_review_session.py tests/test_chief_review_orchestrator.py tests/test_chief_dispatch_policy.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add cad-review-backend/services/audit_runtime/chief_review_session.py cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/services/chief_review_memory_service.py cad-review-backend/services/audit_runtime/chief_dispatch_policy.py cad-review-backend/tests/test_chief_review_session.py cad-review-backend/tests/test_chief_review_orchestrator.py cad-review-backend/tests/test_chief_dispatch_policy.py
git commit -m "feat: add incremental chief assignment dispatch"
```

### Task 3: Collapse visible worker identity onto assignment sessions

**Files:**
- Modify: `cad-review-backend/services/audit_runtime/review_worker_pool.py`
- Modify: `cad-review-backend/services/audit_runtime/agent_runner.py`
- Modify: `cad-review-backend/services/audit_runtime_service.py`
- Modify: `cad-review-backend/routers/audit.py`
- Test: `cad-review-backend/tests/test_review_worker_pool.py`
- Test: `cad-review-backend/tests/test_audit_status_api.py`
- Test: `cad-review-backend/tests/test_runner_broadcast_event_bridge.py`

**Step 1: Write the failing tests**

```python
def test_worker_pool_uses_assignment_id_as_visible_session_key():
    result = asyncio.run(pool.run_batch([assignment_task]))
    assert result[0].meta["visible_session_key"] == "assignment:asg-1"
```

```python
def test_status_api_reports_one_worker_card_per_assignment_even_when_multiple_internal_runner_events_exist(client):
    ...
    assert len(payload["ui_runtime"]["worker_sessions"]) == 1
```

```python
def test_runner_broadcast_keeps_internal_skill_step_but_does_not_create_new_visible_worker_session():
    ...
    assert event["meta"]["assignment_id"] == "asg-1"
```

```python
def test_status_api_does_not_reinflate_worker_cards_when_assignment_and_legacy_events_mix(client):
    ...
    assert len(payload["ui_runtime"]["worker_sessions"]) <= 2
    assert {item["session_key"] for item in payload["ui_runtime"]["worker_sessions"]} == {
        "assignment:asg-1",
        "assignment:asg-2",
    }
```

**Step 2: Run tests to verify they fail**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_review_worker_pool.py tests/test_audit_status_api.py tests/test_runner_broadcast_event_bridge.py -q`

Expected: FAIL because UI runtime still folds cards from low-level runtime session keys.

**Step 3: Implement minimal assignment-scoped worker identity**

```python
meta.update({
    "assignment_id": assignment.assignment_id,
    "visible_session_key": f"assignment:{assignment.assignment_id}",
})
```

```python
def _group_worker_sessions(...):
    group_key = meta.get("visible_session_key") or meta.get("assignment_id") or session_key
```

For migration safety, do not allow legacy raw `session_key` fallback to create extra visible worker cards when assignment-scoped events already exist in the same run. Mixed new/old event streams must collapse onto assignment cards instead of reintroducing the old "64 worker cards" behavior.

**Step 4: Run tests to verify they pass**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_review_worker_pool.py tests/test_audit_status_api.py tests/test_runner_broadcast_event_bridge.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add cad-review-backend/services/audit_runtime/review_worker_pool.py cad-review-backend/services/audit_runtime/agent_runner.py cad-review-backend/services/audit_runtime_service.py cad-review-backend/routers/audit.py cad-review-backend/tests/test_review_worker_pool.py cad-review-backend/tests/test_audit_status_api.py cad-review-backend/tests/test_runner_broadcast_event_bridge.py
git commit -m "feat: bind visible worker cards to assignments"
```

### Task 4: Add worker conclusion contract with Markdown + evidence bundle output

**Files:**
- Create: `cad-review-backend/services/audit_runtime/worker_conclusion_schema.py`
- Modify: `cad-review-backend/services/audit_runtime/worker_skill_contract.py`
- Modify: `cad-review-backend/services/audit_runtime/worker_skills/dimension_consistency_skill.py`
- Modify: `cad-review-backend/services/audit_runtime/worker_skills/node_host_binding_skill.py`
- Modify: `cad-review-backend/services/audit_runtime/worker_skills/material_semantic_skill.py`
- Modify: `cad-review-backend/services/audit_runtime/worker_skills/index_reference_skill.py`
- Test: `cad-review-backend/tests/test_worker_skill_contract.py`
- Test: `cad-review-backend/tests/test_dimension_consistency_skill.py`
- Test: `cad-review-backend/tests/test_node_host_binding_skill.py`

**Step 1: Write the failing tests**

```python
def test_worker_skill_contract_returns_markdown_conclusion_and_evidence_bundle():
    result = build_worker_skill_result(...)
    assert result.markdown_conclusion.startswith("## 任务结论")
    assert result.evidence_bundle["grounding_status"] in {"grounded", "weak", "missing"}
```

```python
def test_dimension_skill_preserves_anchor_payload_in_evidence_bundle(monkeypatch):
    result = asyncio.run(run_dimension_consistency_skill(...))
    assert result.evidence_bundle["anchors"][0]["sheet_no"] == "A1.06"
```

**Step 2: Run tests to verify they fail**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_worker_skill_contract.py tests/test_dimension_consistency_skill.py tests/test_node_host_binding_skill.py -q`

Expected: FAIL because worker results still center on summary/evidence list only.

**Step 3: Implement minimal worker conclusion contract**

```python
class WorkerConclusion(BaseModel):
    markdown_conclusion: str
    evidence_bundle: dict[str, Any]
```

```python
return WorkerResultCard(
    ...
    markdown_conclusion=render_worker_markdown(...),
    evidence_bundle={
        "assignment_id": assignment.assignment_id,
        "evidence_pack_id": ...,
        "anchors": anchors,
        "grounding_status": grounding_status,
        "raw_skill_outputs": [...],
    },
)
```

**Step 4: Run tests to verify they pass**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_worker_skill_contract.py tests/test_dimension_consistency_skill.py tests/test_node_host_binding_skill.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add cad-review-backend/services/audit_runtime/worker_conclusion_schema.py cad-review-backend/services/audit_runtime/worker_skill_contract.py cad-review-backend/services/audit_runtime/worker_skills/dimension_consistency_skill.py cad-review-backend/services/audit_runtime/worker_skills/node_host_binding_skill.py cad-review-backend/services/audit_runtime/worker_skills/material_semantic_skill.py cad-review-backend/services/audit_runtime/worker_skills/index_reference_skill.py cad-review-backend/tests/test_worker_skill_contract.py cad-review-backend/tests/test_dimension_consistency_skill.py cad-review-backend/tests/test_node_host_binding_skill.py
git commit -m "feat: add markdown-first worker conclusion contract"
```

### Task 5: Introduce Final Review Agent and grounding gate

**Files:**
- Create: `cad-review-backend/services/audit_runtime/final_review_agent.py`
- Create: `cad-review-backend/services/audit_runtime/final_review_prompt_assembler.py`
- Modify: `cad-review-backend/services/audit_runtime/orchestrator.py`
- Modify: `cad-review-backend/services/audit_runtime/finding_schema.py`
- Test: `cad-review-backend/tests/test_final_review_agent.py`
- Test: `cad-review-backend/tests/test_chief_review_orchestrator.py`
- Test: `cad-review-backend/tests/test_finding_schema.py`

**Step 1: Write the failing tests**

```python
def test_final_review_rejects_worker_conclusion_without_grounding():
    decision = run_final_review(worker_conclusion=ungrounded_conclusion, ...)
    assert decision.decision == "needs_more_evidence"
```

```python
def test_orchestrator_routes_worker_result_through_final_review_before_accepting():
    ...
    assert captured["final_review_called"] is True
```

```python
def test_finding_schema_validate_grounded_evidence_json_accepts_evidence_bundle_anchors():
    grounded = validate_grounded_evidence_json(payload_json)
    assert len(grounded) == 1
```

```python
def test_orchestrator_routes_redispatch_decision_back_to_chief_dispatch(monkeypatch):
    captured = {"redispatches": 0, "chief_dispatch_called_again": False}
    ...
    assert captured["redispatches"] == 1
    assert captured["chief_dispatch_called_again"] is True
```

**Step 2: Run tests to verify they fail**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_final_review_agent.py tests/test_chief_review_orchestrator.py tests/test_finding_schema.py -q`

Expected: FAIL because no explicit final-review layer exists.

**Step 3: Implement minimal final-review flow**

```python
decision = run_final_review_agent(
    assignment=assignment,
    worker_conclusion=result.markdown_conclusion,
    evidence_bundle=result.evidence_bundle,
)
if decision.decision == "accepted":
    accepted.append(...)
elif decision.decision in {"needs_more_evidence", "redispatch"}:
    queue_followup(...)
```

`queue_followup(...)` must not be implemented as a sink. In particular, `redispatch` must schedule a new chief-dispatch pass carrying the final-review rationale, and the test above must prove that the orchestrator actually re-enters chief dispatch.

**Step 4: Run tests to verify they pass**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_final_review_agent.py tests/test_chief_review_orchestrator.py tests/test_finding_schema.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add cad-review-backend/services/audit_runtime/final_review_agent.py cad-review-backend/services/audit_runtime/final_review_prompt_assembler.py cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/services/audit_runtime/finding_schema.py cad-review-backend/tests/test_final_review_agent.py cad-review-backend/tests/test_chief_review_orchestrator.py cad-review-backend/tests/test_finding_schema.py
git commit -m "feat: add final review agent with grounding gate"
```

### Task 6: Replace finding synthesis with organizer-agent Markdown and FinalIssue conversion

**Files:**
- Create: `cad-review-backend/services/audit_runtime/report_organizer_agent.py`
- Create: `cad-review-backend/services/audit_runtime/final_issue_converter.py`
- Modify: `cad-review-backend/services/audit_runtime/finding_synthesizer.py`
- Modify: `cad-review-backend/services/audit_runtime/orchestrator.py`
- Modify: `cad-review-backend/models.py`
- Test: `cad-review-backend/tests/test_report_organizer_agent.py`
- Test: `cad-review-backend/tests/test_final_issue_converter.py`
- Test: `cad-review-backend/tests/test_chief_review_orchestrator.py`

**Step 1: Write the failing tests**

```python
def test_report_organizer_outputs_markdown_sections_for_accepted_findings():
    markdown = run_report_organizer_agent(accepted_findings=[...])
    assert "## 问题 1" in markdown
```

```python
def test_final_issue_converter_combines_markdown_and_evidence_bundle():
    issue = convert_to_final_issue(...)
    assert issue.issue_code.startswith("ISS-")
    assert issue.anchors[0]["highlight_region"]["bbox_pct"]["width"] > 0
```

```python
def test_orchestrator_persists_final_issue_not_raw_worker_summary():
    ...
    assert stored.evidence_json["anchors"][0]["sheet_no"] == "A1.06"
```

**Step 2: Run tests to verify they fail**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_report_organizer_agent.py tests/test_final_issue_converter.py tests/test_chief_review_orchestrator.py -q`

Expected: FAIL because final persistence still stores simplified `finding` payloads.

**Step 3: Implement minimal organizer + converter**

```python
markdown = run_report_organizer_agent(accepted_decisions=accepted_decisions)
final_issues = convert_markdown_and_evidence_to_final_issues(
    organizer_markdown=markdown,
    accepted_decisions=accepted_decisions,
)
```

```python
evidence_json = {
    "anchors": issue.anchors,
    "evidence_pack_id": issue.evidence_pack_id,
    "finding": issue.model_dump(),
}
```

At the end of this task, `finding_synthesizer.py` must no longer be directly used by `orchestrator.py` for the primary accepted-results path. If compatibility helpers remain, keep them explicitly as test/compatibility entrypoints only and document that organizer + converter is now the authoritative path.

**Step 4: Run tests to verify they pass**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_report_organizer_agent.py tests/test_final_issue_converter.py tests/test_chief_review_orchestrator.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add cad-review-backend/services/audit_runtime/report_organizer_agent.py cad-review-backend/services/audit_runtime/final_issue_converter.py cad-review-backend/services/audit_runtime/finding_synthesizer.py cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/models.py cad-review-backend/tests/test_report_organizer_agent.py cad-review-backend/tests/test_final_issue_converter.py cad-review-backend/tests/test_chief_review_orchestrator.py
git commit -m "feat: add organizer agent and final issue conversion"
```

### Task 7: Rebuild runtime UI around assignments, final review, and organizer stages

**Files:**
- Modify: `cad-review-frontend/src/types/index.ts`
- Modify: `cad-review-frontend/src/pages/ProjectDetail/components/useAuditProgressViewModel.ts`
- Modify: `cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx`
- Modify: `cad-review-frontend/src/pages/ProjectDetail.tsx`
- Test: `cad-review-frontend/src/pages/ProjectDetail/components/__tests__/useAuditProgressViewModel.test.ts`
- Test: `cad-review-frontend/src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx`
- Test: `cad-review-frontend/src/pages/ProjectDetail/__tests__/ProjectDetail.auditState.test.ts`

**Step 1: Write the failing tests**

```ts
it("shows one worker card per assignment even when internal skill actions are many", () => {
  const viewModel = buildAuditProgressViewModel(statusPayloadWithAssignmentScopedUiRuntime)
  expect(viewModel.workerWall.active).toHaveLength(2)
})
```

```ts
it("renders final review and organizer states separately from worker cards", () => {
  render(<AuditProgressDialog ... />)
  expect(screen.getByText("终审复核")).toBeInTheDocument()
  expect(screen.getByText("汇总整理")).toBeInTheDocument()
})
```

**Step 2: Run tests to verify they fail**

Run: `cd cad-review-frontend && pnpm vitest run src/pages/ProjectDetail/components/__tests__/useAuditProgressViewModel.test.ts src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx src/pages/ProjectDetail/__tests__/ProjectDetail.auditState.test.ts --environment jsdom`

Expected: FAIL because current UI runtime only models chief + worker wall + debug drawer.

**Step 3: Implement minimal UI changes**

```ts
type AuditUiRuntime = {
  chief: ChiefCardViewModel
  worker_sessions: WorkerSessionCardViewModel[]
  final_review: FinalReviewCardViewModel
  organizer: OrganizerCardViewModel
  ...
}
```

```tsx
<ChiefCard ... />
<WorkerWall sessions={workerWall.active} />
<FinalReviewCard finalReview={viewModel.finalReview} />
<OrganizerCard organizer={viewModel.organizer} />
```

**Step 4: Run tests to verify they pass**

Run: `cd cad-review-frontend && pnpm vitest run src/pages/ProjectDetail/components/__tests__/useAuditProgressViewModel.test.ts src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx src/pages/ProjectDetail/__tests__/ProjectDetail.auditState.test.ts --environment jsdom`

Expected: PASS.

**Step 5: Commit**

```bash
git add cad-review-frontend/src/types/index.ts cad-review-frontend/src/pages/ProjectDetail/components/useAuditProgressViewModel.ts cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx cad-review-frontend/src/pages/ProjectDetail.tsx cad-review-frontend/src/pages/ProjectDetail/components/__tests__/useAuditProgressViewModel.test.ts cad-review-frontend/src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx cad-review-frontend/src/pages/ProjectDetail/__tests__/ProjectDetail.auditState.test.ts
git commit -m "feat: surface assignment, final review, and organizer runtime states"
```

### Task 8: Preserve grounding through persistence and restore marked report reliability

**Files:**
- Modify: `cad-review-backend/services/report_service.py`
- Modify: `cad-review-backend/services/audit_runtime/orchestrator.py`
- Modify: `cad-review-backend/services/audit_runtime/finding_schema.py`
- Test: `cad-review-backend/tests/test_report_service.py`
- Test: `cad-review-backend/tests/test_finding_schema.py`
- Test: `cad-review-backend/tests/test_chief_review_orchestrator.py`

**Step 1: Write the failing tests**

```python
def test_generate_marked_report_uses_final_issue_anchor_bbox_when_available():
    result = generate_pdf_marked(project, [audit_result_with_final_issue_anchor], version=3, db=db)
    assert result["mode"] == "marked"
```

```python
def test_orchestrator_persists_grounding_payload_for_marked_report():
    ...
    assert payload["anchors"][0]["highlight_region"]["bbox_pct"]["height"] > 0
```

**Step 2: Run tests to verify they fail**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_report_service.py tests/test_finding_schema.py tests/test_chief_review_orchestrator.py -q`

Expected: FAIL because persistence still does not guarantee final grounding payloads are stable.

**Step 3: Implement minimal grounding-preserving persistence**

```python
evidence_json = merge_finding_into_evidence_json(existing_payload, finding)
payload["anchors"] = final_issue.anchors
payload["grounding"] = {"status": "grounded", "anchor_count": len(final_issue.anchors)}
```

**Step 4: Run tests to verify they pass**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_report_service.py tests/test_finding_schema.py tests/test_chief_review_orchestrator.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add cad-review-backend/services/report_service.py cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/services/audit_runtime/finding_schema.py cad-review-backend/tests/test_report_service.py cad-review-backend/tests/test_finding_schema.py cad-review-backend/tests/test_chief_review_orchestrator.py
git commit -m "fix: preserve grounding through final issue persistence"
```

### Task 9: Add migration, docs, and real-project acceptance verification

**Files:**
- Modify: `cad-review-backend/README.md`
- Modify: `cad-review-frontend/README.md`
- Modify: `cad-review-backend/utils/manual_check_ai_review_flow.py`
- Create: `cad-review-backend/tests/test_manual_check_assignment_final_review_modes.py`
- Modify: `docs/plans/2026-03-12-chief-review-assignment-final-review-architecture-design.md`

**Step 1: Write the failing verification test**

```python
def test_manual_check_supports_assignment_final_review_mode():
    payload = run_manual_check(mode="assignment_final_review", ...)
    assert payload["pipeline_mode"] == "assignment_final_review"
```

**Step 2: Run test to verify it fails**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_manual_check_assignment_final_review_modes.py -q`

Expected: FAIL because the manual check tool does not yet expose the new mode.

**Step 3: Implement the minimal verification tooling and docs updates**

```python
SUPPORTED_MODES = {"legacy", "chief_review", "shadow_compare", "assignment_final_review"}
```

- Update README acceptance criteria to state:
  - one worker card per assignment
  - explicit final-review stage
  - organizer Markdown output
  - marked report requires grounded final issues

**Step 4: Run tests and one real-project acceptance pass**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_manual_check_assignment_final_review_modes.py -q`

Expected: PASS.

Run on real project after implementation:

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && \
./venv/bin/python utils/manual_check_ai_review_flow.py \
  --project-id proj_20260309231506_001af8d5 \
  --mode assignment_final_review \
  --provider-mode api
```

Acceptance expectations:

- visible worker card count never exceeds assignment count
- final review appears in runtime status
- organizer output is Markdown-first
- final report carries grounded anchors and marked report is generated

**Step 5: Commit**

```bash
git add cad-review-backend/README.md cad-review-frontend/README.md cad-review-backend/utils/manual_check_ai_review_flow.py cad-review-backend/tests/test_manual_check_assignment_final_review_modes.py docs/plans/2026-03-12-chief-review-assignment-final-review-architecture-design.md
git commit -m "docs: add assignment final review acceptance path"
```

### Verification Matrix

Backend targeted:

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && \
./venv/bin/pytest \
  tests/test_review_task_schema.py \
  tests/test_final_review_schema.py \
  tests/test_chief_review_session.py \
  tests/test_chief_dispatch_policy.py \
  tests/test_review_worker_pool.py \
  tests/test_worker_skill_contract.py \
  tests/test_final_review_agent.py \
  tests/test_report_organizer_agent.py \
  tests/test_final_issue_converter.py \
  tests/test_audit_status_api.py \
  tests/test_runner_broadcast_event_bridge.py \
  tests/test_report_service.py \
  tests/test_manual_check_assignment_final_review_modes.py -q
```

Frontend targeted:

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && \
pnpm vitest run \
  src/pages/ProjectDetail/components/__tests__/useAuditProgressViewModel.test.ts \
  src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx \
  src/pages/ProjectDetail/__tests__/ProjectDetail.auditState.test.ts \
  --environment jsdom
```

Real-project acceptance:

- Use `test1` (`proj_20260309231506_001af8d5`) in real `api` mode.
- Confirm assignment count grows incrementally instead of being fully known at start.
- Confirm visible worker card count never exceeds assignment count.
- Confirm final review can return `accepted`, `needs_more_evidence`, and `redispatch`.
- Confirm organizer output is Markdown and converter persists grounded `FinalIssue`.
- Confirm marked report uses `anchors` from final issues rather than fallback-only text locations.
