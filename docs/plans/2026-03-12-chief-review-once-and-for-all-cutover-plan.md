# Chief Review Once-And-For-All Cutover Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Finish the chief-review cutover so the runtime, worker skills, evidence flow, UI wording, and validation path all consistently operate around `chief_review + review_worker` instead of the old stage-driven pipeline.

**Architecture:** Keep the current `chief_review` orchestration skeleton, but remove the remaining “new shell / old brain” gaps. The cutover should make `chief_review` the real decision center, move worker execution to native skill-first paths, wire sheet graph and cross-sheet evidence services into the actual runtime, and demote legacy stage prompts and wrappers to explicit compatibility-only codepaths.

**Tech Stack:** Python, FastAPI, SQLAlchemy, pytest, React, Vite, Vitest

---

### Task 1: Lock cutover policy and fix the worker compatibility regression

**Files:**
- Modify: `cad-review-backend/services/audit_runtime/orchestrator.py`
- Modify: `cad-review-backend/services/audit_runtime/review_worker_runtime.py`
- Test: `cad-review-backend/tests/test_chief_review_compatibility_bridge.py`
- Test: `cad-review-backend/tests/test_pipeline_mode_cutover.py`

**Step 1: Write the failing regression test**

```python
def test_default_chief_worker_runner_dispatches_to_dimension_wrapper(monkeypatch):
    ...
    assert called["value"] is True
    assert result.meta["compat_mode"] == "worker_wrapper"
```

**Step 2: Run test to verify it fails**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_chief_review_compatibility_bridge.py::test_default_chief_worker_runner_dispatches_to_dimension_wrapper -q`

Expected: FAIL because `_default_chief_worker_runner()` currently returns `None`/native-only behavior instead of explicit wrapper fallback.

**Step 3: Implement minimal compatibility routing**

```python
async def _default_chief_worker_runner(task):
    native_result = await run_native_review_worker(task=task, db=db)
    if native_result is not None:
        return native_result
    return _run_compat_worker_wrapper(task, db=db)
```

```python
def _run_compat_worker_wrapper(task, db):
    if task.worker_kind in {"elevation_consistency", "spatial_consistency"}:
        return run_dimension_worker_wrapper(...)
    if task.worker_kind == "index_reference":
        return run_index_worker_wrapper(...)
    if task.worker_kind == "material_semantic_consistency":
        return run_material_worker_wrapper(...)
    if task.worker_kind == "node_host_binding":
        return run_relationship_worker_wrapper(...)
```

**Step 4: Run cutover tests**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_chief_review_compatibility_bridge.py tests/test_pipeline_mode_cutover.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/services/audit_runtime/review_worker_runtime.py cad-review-backend/tests/test_chief_review_compatibility_bridge.py cad-review-backend/tests/test_pipeline_mode_cutover.py
git commit -m "fix: restore chief review worker compatibility fallback"
```

### Task 2: Make `SheetGraph` actually LLM-first on the chief path

**Files:**
- Modify: `cad-review-backend/services/audit_runtime/sheet_graph_builder.py`
- Modify: `cad-review-backend/services/audit_runtime/sheet_graph_semantic_builder.py`
- Modify: `cad-review-backend/services/audit_runtime/orchestrator.py`
- Modify: `cad-review-backend/services/audit_runtime/chief_review_planner.py`
- Test: `cad-review-backend/tests/test_sheet_graph_builder.py`
- Test: `cad-review-backend/tests/test_chief_review_orchestrator.py`

**Step 1: Add a failing orchestration test for semantic runner injection**

```python
def test_execute_pipeline_chief_review_builds_sheet_graph_with_semantic_runner(monkeypatch):
    captured = {}
    def fake_build_sheet_graph(*, sheet_contexts, sheet_edges, llm_runner=None):
        captured["llm_runner"] = llm_runner
        return SimpleNamespace(sheet_types={}, linked_targets={}, node_hosts={})
    ...
    assert callable(captured["llm_runner"])
```

**Step 2: Run the targeted tests**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_sheet_graph_builder.py tests/test_chief_review_orchestrator.py -q`

Expected: FAIL because the chief path currently calls `build_sheet_graph(...)` without an LLM semantic runner.

**Step 3: Implement semantic runner plumbing**

```python
def build_sheet_graph(..., llm_runner=None):
    candidates = build_sheet_graph_candidates(...)
    return build_sheet_graph_from_candidates(candidates=candidates, llm_runner=llm_runner)
```

```python
sheet_graph = build_sheet_graph(
    sheet_contexts=contexts,
    sheet_edges=edges,
    llm_runner=_chief_sheet_graph_semantic_runner(...),
)
```

```python
planner_meta["sheet_graph_semantics_source"] = "llm_runner"
```

**Step 4: Re-run the tests**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_sheet_graph_builder.py tests/test_chief_review_orchestrator.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add cad-review-backend/services/audit_runtime/sheet_graph_builder.py cad-review-backend/services/audit_runtime/sheet_graph_semantic_builder.py cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/services/audit_runtime/chief_review_planner.py cad-review-backend/tests/test_sheet_graph_builder.py cad-review-backend/tests/test_chief_review_orchestrator.py
git commit -m "feat: wire llm-first sheet graph into chief review flow"
```

### Task 3: Wire `cross_sheet_locator` and `evidence_prefetch_service` into native worker execution

**Files:**
- Modify: `cad-review-backend/services/audit_runtime/worker_skills/dimension_consistency_skill.py`
- Modify: `cad-review-backend/services/audit_runtime/worker_skills/node_host_binding_skill.py`
- Modify: `cad-review-backend/services/audit_runtime/worker_skills/index_reference_skill.py`
- Modify: `cad-review-backend/services/audit_runtime/evidence_prefetch_service.py`
- Test: `cad-review-backend/tests/test_cross_sheet_locator.py`
- Test: `cad-review-backend/tests/test_evidence_prefetch_service.py`
- Test: `cad-review-backend/tests/test_dimension_consistency_skill.py`
- Test: `cad-review-backend/tests/test_node_host_binding_skill.py`

**Step 1: Add failing worker integration tests**

```python
def test_dimension_skill_uses_cross_sheet_locator_and_prefetch(monkeypatch):
    ...
    assert called["locate"] is True
    assert called["prefetch"] is True
```

```python
def test_node_host_binding_skill_prefetches_target_regions(monkeypatch):
    ...
    assert batch.unique_request_count >= 1
```

**Step 2: Run the targeted tests**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_cross_sheet_locator.py tests/test_evidence_prefetch_service.py tests/test_dimension_consistency_skill.py tests/test_node_host_binding_skill.py -q`

Expected: FAIL because the native skills currently call old internals directly and do not route through `cross_sheet_locator` + `prefetch_regions()`.

**Step 3: Implement service-first execution**

```python
pairs = locate_across_sheets(...)
batch = await prefetch_regions(requests=_build_worker_evidence_requests(...))
```

```python
meta.update({
    "anchor_pair_count": len(pairs),
    "prefetch_cache_hits": batch.cache_hits,
    "evidence_service_mode": "prefetch",
})
```

**Step 4: Re-run the tests**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_cross_sheet_locator.py tests/test_evidence_prefetch_service.py tests/test_dimension_consistency_skill.py tests/test_node_host_binding_skill.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add cad-review-backend/services/audit_runtime/worker_skills/dimension_consistency_skill.py cad-review-backend/services/audit_runtime/worker_skills/node_host_binding_skill.py cad-review-backend/services/audit_runtime/worker_skills/index_reference_skill.py cad-review-backend/services/audit_runtime/evidence_prefetch_service.py cad-review-backend/tests/test_cross_sheet_locator.py cad-review-backend/tests/test_evidence_prefetch_service.py cad-review-backend/tests/test_dimension_consistency_skill.py cad-review-backend/tests/test_node_host_binding_skill.py
git commit -m "feat: route native workers through locator and evidence prefetch"
```

### Task 4: Remove legacy stage prompts from the chief path and confine them to compatibility-only flows

**Files:**
- Modify: `cad-review-backend/services/ai_prompt_service.py`
- Modify: `cad-review-backend/services/audit_runtime/runtime_prompt_assembler.py`
- Modify: `cad-review-backend/services/audit_runtime/worker_skills/dimension_consistency_skill.py`
- Modify: `cad-review-backend/services/audit_runtime/worker_skills/node_host_binding_skill.py`
- Modify: `cad-review-backend/services/audit_runtime/worker_skills/material_semantic_skill.py`
- Modify: `cad-review-backend/services/audit_runtime/worker_skills/index_reference_skill.py`
- Test: `cad-review-backend/tests/test_ai_prompt_service.py`
- Test: `cad-review-backend/tests/test_runtime_prompt_assembler.py`

**Step 1: Add failing tests that assert chief/native paths no longer depend on legacy stage metadata**

```python
def test_worker_runtime_prompt_bundle_prefers_agent_skill_without_legacy_stage_meta():
    bundle = assemble_worker_runtime_prompt(worker_kind="index_reference", task_context={...})
    assert bundle.meta["prompt_source"] == "agent_skill"
    assert "replacement" not in bundle.meta
```

**Step 2: Run the targeted tests**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_ai_prompt_service.py tests/test_runtime_prompt_assembler.py -q`

Expected: FAIL because the current runtime still keeps legacy prompt metadata and old stage prompt definitions as first-class runtime objects.

**Step 3: Implement prompt demotion**

```python
PromptStageDefinition(..., lifecycle="legacy_template_compat", is_primary_runtime_source=False)
```

```python
assemble_worker_runtime_prompt(...):
    # only agent/review_worker assets + SKILL.md
```

```python
legacy stage prompts remain callable only from explicit wrapper/legacy entrypoints
```

**Step 4: Re-run the tests**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_ai_prompt_service.py tests/test_runtime_prompt_assembler.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add cad-review-backend/services/ai_prompt_service.py cad-review-backend/services/audit_runtime/runtime_prompt_assembler.py cad-review-backend/services/audit_runtime/worker_skills/dimension_consistency_skill.py cad-review-backend/services/audit_runtime/worker_skills/node_host_binding_skill.py cad-review-backend/services/audit_runtime/worker_skills/material_semantic_skill.py cad-review-backend/services/audit_runtime/worker_skills/index_reference_skill.py cad-review-backend/tests/test_ai_prompt_service.py cad-review-backend/tests/test_runtime_prompt_assembler.py
git commit -m "refactor: confine legacy prompts to compatibility-only flows"
```

### Task 5: Finish native worker cutover and demote wrappers to explicit legacy fallback

**Files:**
- Modify: `cad-review-backend/services/audit_runtime/worker_skill_registry.py`
- Modify: `cad-review-backend/services/audit_runtime/review_worker_runtime.py`
- Modify: `cad-review-backend/services/audit/dimension_audit.py`
- Modify: `cad-review-backend/services/audit/index_audit.py`
- Modify: `cad-review-backend/services/audit/material_audit.py`
- Modify: `cad-review-backend/services/audit/relationship_discovery.py`
- Test: `cad-review-backend/tests/test_worker_skill_dispatch.py`
- Test: `cad-review-backend/tests/test_chief_review_compatibility_bridge.py`

**Step 1: Add failing dispatch tests for native-first behavior**

```python
def test_native_review_worker_returns_native_card_before_wrapper(monkeypatch):
    ...
    assert result.meta["compat_mode"] == "native_worker"
```

```python
def test_wrapper_path_is_only_used_when_skill_executor_missing(monkeypatch):
    ...
    assert result.meta["compat_mode"] == "worker_wrapper"
```

**Step 2: Run the targeted tests**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_worker_skill_dispatch.py tests/test_chief_review_compatibility_bridge.py -q`

Expected: FAIL until the registry/runtime explicitly separates native execution from wrapper fallback.

**Step 3: Implement native-first dispatch rules**

```python
if get_worker_skill_executor(worker_kind):
    return await executor.execute(...)
return None
```

```python
run_*_worker_wrapper(...):
    # keep only as compatibility bridge, never as primary chief path when native skill exists
```

**Step 4: Re-run the tests**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_worker_skill_dispatch.py tests/test_chief_review_compatibility_bridge.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add cad-review-backend/services/audit_runtime/worker_skill_registry.py cad-review-backend/services/audit_runtime/review_worker_runtime.py cad-review-backend/services/audit/dimension_audit.py cad-review-backend/services/audit/index_audit.py cad-review-backend/services/audit/material_audit.py cad-review-backend/services/audit/relationship_discovery.py cad-review-backend/tests/test_worker_skill_dispatch.py cad-review-backend/tests/test_chief_review_compatibility_bridge.py
git commit -m "refactor: make worker skills native-first and wrappers fallback-only"
```

### Task 6: Rewrite runtime events and frontend progress UI around chief/worker language

**Files:**
- Modify: `cad-review-backend/services/audit_runtime/orchestrator.py`
- Modify: `cad-review-backend/services/settings_runtime_summary_service.py`
- Modify: `cad-review-frontend/src/pages/ProjectDetail/components/useAuditProgressViewModel.ts`
- Modify: `cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx`
- Modify: `cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx`
- Test: `cad-review-backend/tests/test_settings_runtime_summary_api.py`
- Test: `cad-review-frontend/src/pages/ProjectDetail/components/__tests__/useAuditProgressViewModel.test.ts`
- Test: `cad-review-frontend/src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx`

**Step 1: Add failing presentation tests**

```tsx
it('renders chief summary and worker lanes without legacy stage wording', () => {
  expect(screen.getByText('主审准备')).toBeInTheDocument();
  expect(screen.queryByText('尺寸核对')).not.toBeInTheDocument();
});
```

**Step 2: Run the targeted tests**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_settings_runtime_summary_api.py -q && cd ../cad-review-frontend && npm test -- --run src/pages/ProjectDetail/components/__tests__/useAuditProgressViewModel.test.ts src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx`

Expected: FAIL because the frontend still infers many states from old `turn_kind` / legacy stage names.

**Step 3: Implement chief/worker-native view models**

```ts
resolveSkillLabel(event) {
  if (meta.skill_id === 'index_reference') return '索引引用 Skill';
  ...
}
```

```python
append_run_event(... meta={"planner_source": "chief_review_agent", "skill_mode": "worker_skill", ...})
```

**Step 4: Re-run the tests**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_settings_runtime_summary_api.py -q && cd ../cad-review-frontend && npm test -- --run src/pages/ProjectDetail/components/__tests__/useAuditProgressViewModel.test.ts src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx`

Expected: PASS.

**Step 5: Commit**

```bash
git add cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/services/settings_runtime_summary_service.py cad-review-frontend/src/pages/ProjectDetail/components/useAuditProgressViewModel.ts cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx cad-review-backend/tests/test_settings_runtime_summary_api.py cad-review-frontend/src/pages/ProjectDetail/components/__tests__/useAuditProgressViewModel.test.ts cad-review-frontend/src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx
git commit -m "refactor: align runtime events and ui with chief worker model"
```

### Task 7: Finish shadow compare as business validation, not just framework smoke

**Files:**
- Modify: `cad-review-backend/utils/manual_check_ai_review_flow.py`
- Modify: `cad-review-backend/README.md`
- Modify: `cad-review-frontend/README.md`
- Test: `cad-review-backend/tests/test_manual_check_shadow_modes.py`

**Step 1: Add failing acceptance test for richer shadow compare summary**

```python
def test_shadow_compare_summary_includes_overlap_and_duration_delta():
    summary = build_shadow_compare_summary(...)
    assert "duration_delta_seconds" in summary
    assert "ready_for_cutover" in summary
```

**Step 2: Run the targeted test**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_manual_check_shadow_modes.py -q`

Expected: FAIL because `shadow_compare` currently reports framework overlap only.

**Step 3: Implement business-level comparison summary**

```python
summary = {
    "legacy_result_count": ...,
    "chief_review_result_count": ...,
    "overlap_ratio": ...,
    "duration_delta_seconds": ...,
    "ready_for_cutover": bool(...),
}
```

Update README with one explicit cutover gate:

- overlap threshold
- acceptable missing/new finding range
- failure conditions

**Step 4: Re-run the test**

Run: `cd cad-review-backend && ./venv/bin/pytest tests/test_manual_check_shadow_modes.py -q`

Expected: PASS.

**Step 5: Commit**

```bash
git add cad-review-backend/utils/manual_check_ai_review_flow.py cad-review-backend/README.md cad-review-frontend/README.md cad-review-backend/tests/test_manual_check_shadow_modes.py
git commit -m "chore: promote shadow compare to business cutover validation"
```

### Task 8: Final verification sweep and remove unfinished cutover ambiguity

**Files:**
- Modify: `cad-review-backend/README.md`
- Modify: `cad-review-frontend/README.md`
- Test: `cad-review-backend/tests/test_agent_asset_service.py`
- Test: `cad-review-backend/tests/test_chief_review_memory_service.py`
- Test: `cad-review-backend/tests/test_sheet_graph_builder.py`
- Test: `cad-review-backend/tests/test_cross_sheet_locator.py`
- Test: `cad-review-backend/tests/test_evidence_prefetch_service.py`
- Test: `cad-review-backend/tests/test_chief_review_session.py`
- Test: `cad-review-backend/tests/test_review_worker_pool.py`
- Test: `cad-review-backend/tests/test_chief_review_planner.py`
- Test: `cad-review-backend/tests/test_chief_review_orchestrator.py`
- Test: `cad-review-backend/tests/test_finding_synthesizer.py`
- Test: `cad-review-backend/tests/test_worker_skill_dispatch.py`
- Test: `cad-review-backend/tests/test_chief_review_compatibility_bridge.py`
- Test: `cad-review-backend/tests/test_pipeline_mode_cutover.py`
- Test: `cad-review-backend/tests/test_manual_check_shadow_modes.py`
- Test: `cad-review-backend/tests/test_settings_runtime_summary_api.py`
- Test: `cad-review-frontend/src/pages/settings/__tests__/SettingsPrompts.test.tsx`
- Test: `cad-review-frontend/src/pages/settings/__tests__/SettingsReviewWorkerSkills.test.tsx`
- Test: `cad-review-frontend/src/pages/settings/__tests__/SettingsRuntimeSummary.test.tsx`

**Step 1: Run backend verification suite**

Run:

```bash
cd cad-review-backend
./venv/bin/pytest \
  tests/test_agent_asset_service.py \
  tests/test_chief_review_memory_service.py \
  tests/test_sheet_graph_builder.py \
  tests/test_cross_sheet_locator.py \
  tests/test_evidence_prefetch_service.py \
  tests/test_chief_review_session.py \
  tests/test_review_worker_pool.py \
  tests/test_chief_review_planner.py \
  tests/test_chief_review_orchestrator.py \
  tests/test_finding_synthesizer.py \
  tests/test_worker_skill_dispatch.py \
  tests/test_chief_review_compatibility_bridge.py \
  tests/test_pipeline_mode_cutover.py \
  tests/test_manual_check_shadow_modes.py \
  tests/test_settings_runtime_summary_api.py -q
```

Expected: PASS.

**Step 2: Run frontend verification suite**

Run:

```bash
cd cad-review-frontend
npm test -- --run \
  src/pages/settings/__tests__/SettingsPrompts.test.tsx \
  src/pages/settings/__tests__/SettingsReviewWorkerSkills.test.tsx \
  src/pages/settings/__tests__/SettingsRuntimeSummary.test.tsx
```

Expected: PASS.

**Step 3: Run one manual cutover check**

Run:

```bash
cd cad-review-backend
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <project_id> --provider-mode api --run-mode shadow_compare --wait-seconds 90
```

Expected: produces overlap, diff, duration, and cutover recommendation fields.

**Step 4: Update docs to remove half-cutover wording**

- Mark `chief_review` as primary production path.
- State exactly which wrappers remain for legacy fallback.
- Remove README language that implies the migration is still mostly conceptual.

**Step 5: Commit**

```bash
git add cad-review-backend/README.md cad-review-frontend/README.md
git commit -m "chore: finalize chief review cutover verification"
```

## Execution Order

1. Task 1 first, because the compatibility regression is already red.
2. Task 2 and Task 3 next, because they convert the current shell into the intended LLM-first runtime.
3. Task 4 and Task 5 after that, to stop legacy prompts and wrappers from remaining in the hot path.
4. Task 6 then aligns runtime events and frontend presentation with the new system.
5. Task 7 promotes shadow compare from framework smoke test to actual rollout evidence.
6. Task 8 is the final verification gate. Do not call this cutover complete before it passes.

## Completion Criteria

- `chief_review` remains the default runtime path without hidden dependency on legacy stage planning.
- `SheetGraph` semantics and cross-sheet locating are actually exercised in the chief runtime, not just by isolated tests.
- Native worker skills are primary for `index_reference`, `material_semantic_consistency`, `node_host_binding`, `elevation_consistency`, and `spatial_consistency`.
- Legacy wrappers and stage prompts remain only as explicit fallback/compatibility codepaths.
- Runtime events, summaries, and frontend progress UI all describe the system in chief/worker language.
- `shadow_compare` produces business-level rollout evidence, not just framework-level smoke output.
