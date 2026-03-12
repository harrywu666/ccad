# 主审 + 副审群审图重构实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 把现有“总控 + 关系/尺寸/材料 Agent”的任务流水线，重构成“常驻主审 + 副审群 + LLM-first 跨图定位/证据服务”的审图系统。

**架构：** 保留现有 Kimi SDK runner 和事件总线，但把业务决策中心从 `master_task_planner + task_planner + 专项 Agent` 换成 `chief_review_agent + worker dispatcher + sheet graph + project memory`。`AGENTS.md / SOUL.md / MEMORY.md` 成为主资源，`PROMPT` 退居组装层，JSON 与代码只承担候选整理、缓存、调度、校验、恢复；真正的图纸语义建图和跨图定位由 LLM worker 完成。

**技术栈：** Python / FastAPI / SQLAlchemy / pytest / React / Vite / Kimi SDK Runner / 现有 audit_runtime 事件流

---

### 任务 1：建立 Agent 资源目录和通用资源加载层

**文件：**
- 创建：`cad-review-backend/agents/chief_review/AGENTS.md`
- 创建：`cad-review-backend/agents/chief_review/SOUL.md`
- 创建：`cad-review-backend/agents/chief_review/MEMORY.md`
- 创建：`cad-review-backend/agents/runtime_guardian/AGENTS.md`
- 创建：`cad-review-backend/agents/runtime_guardian/SOUL.md`
- 创建：`cad-review-backend/agents/runtime_guardian/MEMORY.md`
- 创建：`cad-review-backend/agents/review_worker/AGENTS.md`
- 创建：`cad-review-backend/agents/review_worker/SOUL.md`
- 创建：`cad-review-backend/agents/review_worker/MEMORY.md`
- 创建：`cad-review-backend/services/agent_asset_service.py`
- 创建：`cad-review-backend/tests/test_agent_asset_service.py`
- 修改：`cad-review-backend/services/ai_prompt_service.py`
- 修改：`cad-review-backend/routers/settings.py`

**步骤 1：编写失败的测试**

```python
def test_agent_asset_service_reads_agent_soul_memory():
    bundle = load_agent_assets("chief_review")
    assert bundle.agent_markdown.startswith("#")
    assert bundle.soul_markdown.startswith("#")
    assert bundle.memory_markdown.startswith("#")
```

**步骤 2：运行测试验证它失败**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_agent_asset_service.py -v`
预期：FAIL，提示 `load_agent_assets` 或资源目录不存在。

**步骤 3：编写最小实现**

```python
@dataclass(frozen=True)
class AgentAssetBundle:
    agent_markdown: str
    soul_markdown: str
    memory_markdown: str

def load_agent_assets(agent_id: str) -> AgentAssetBundle:
    base = AGENTS_ROOT / agent_id
    return AgentAssetBundle(
        agent_markdown=(base / "AGENTS.md").read_text(encoding="utf-8"),
        soul_markdown=(base / "SOUL.md").read_text(encoding="utf-8"),
        memory_markdown=(base / "MEMORY.md").read_text(encoding="utf-8"),
    )
```

**步骤 4：运行测试验证它通过**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_agent_asset_service.py -v`
预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/agents cad-review-backend/services/agent_asset_service.py cad-review-backend/tests/test_agent_asset_service.py cad-review-backend/services/ai_prompt_service.py cad-review-backend/routers/settings.py
git commit -m "feat: add agent asset loading"
```

### 任务 2：引入 ProjectMemory 和两段式 SheetGraph 构建

**文件：**
- 创建：`cad-review-backend/services/chief_review_memory_service.py`
- 创建：`cad-review-backend/services/audit_runtime/sheet_graph_candidates_builder.py`
- 创建：`cad-review-backend/services/audit_runtime/sheet_graph_semantic_builder.py`
- 创建：`cad-review-backend/services/audit_runtime/sheet_graph_builder.py`
- 创建：`cad-review-backend/services/audit_runtime/project_memory_store.py`
- 创建：`cad-review-backend/tests/test_sheet_graph_builder.py`
- 创建：`cad-review-backend/tests/test_chief_review_memory_service.py`
- 修改：`cad-review-backend/models.py`
- 修改：`cad-review-backend/database.py`

**步骤 1：编写失败的测试**

```python
def test_build_sheet_graph_groups_plan_ceiling_elevation_detail():
    graph = build_sheet_graph(sheet_contexts=[...], sheet_edges=[...])
    assert graph.sheet_types["A1-01"] == "plan"
    assert "A4-02" in graph.linked_targets["A1-01"]
```

```python
def test_sheet_graph_semantic_builder_uses_llm_to_confirm_sheet_types(monkeypatch):
    graph = build_sheet_graph_from_candidates(candidates=..., llm_runner=...)
    assert graph.sheet_types["A4-02"] == "detail"
```

```python
def test_project_memory_persists_hypothesis_pool():
    memory = save_project_memory(project_id="p1", audit_version=1, payload={...})
    assert memory["active_hypotheses"][0]["topic"] == "标高一致性"
```

**步骤 2：运行测试验证它失败**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_sheet_graph_builder.py tests/test_chief_review_memory_service.py -v`
预期：FAIL，提示缺少服务或模型字段。

**步骤 3：编写最小实现**

```python
class SheetGraph(BaseModel):
    sheet_types: dict[str, str]
    linked_targets: dict[str, list[str]]
    node_hosts: dict[str, list[str]]

def build_sheet_graph(...):
    candidates = build_sheet_graph_candidates(...)
    return build_sheet_graph_from_candidates(candidates=candidates, llm_runner=...)

class ProjectMemoryRecord(Base):
    __tablename__ = "project_memory_records"
    project_id = Column(String, nullable=False, index=True)
    audit_version = Column(Integer, nullable=False, index=True)
    memory_json = Column(Text, nullable=False)
```

**步骤 4：运行测试验证它通过**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_sheet_graph_builder.py tests/test_chief_review_memory_service.py -v`
预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/chief_review_memory_service.py cad-review-backend/services/audit_runtime/sheet_graph_candidates_builder.py cad-review-backend/services/audit_runtime/sheet_graph_semantic_builder.py cad-review-backend/services/audit_runtime/sheet_graph_builder.py cad-review-backend/services/audit_runtime/project_memory_store.py cad-review-backend/models.py cad-review-backend/database.py cad-review-backend/tests/test_sheet_graph_builder.py cad-review-backend/tests/test_chief_review_memory_service.py
git commit -m "feat: add project memory and sheet graph"
```

### 任务 3：增加 LLM-first 跨图定位和证据预取服务

**文件：**
- 创建：`cad-review-backend/services/audit_runtime/cross_sheet_index.py`
- 创建：`cad-review-backend/services/audit_runtime/cross_sheet_locator.py`
- 创建：`cad-review-backend/services/audit_runtime/evidence_prefetch_service.py`
- 创建：`cad-review-backend/tests/test_cross_sheet_locator.py`
- 创建：`cad-review-backend/tests/test_evidence_prefetch_service.py`
- 修改：`cad-review-backend/services/audit_runtime/evidence_service.py`
- 修改：`cad-review-backend/services/audit_runtime/hot_sheet_registry.py`

**步骤 1：编写失败的测试**

```python
def test_cross_sheet_locator_returns_anchor_pairs_for_elevation_check():
    pairs = locate_across_sheets(
        source_sheet_no="A3-01",
        target_sheet_nos=["A2-01", "A1-01"],
        anchor_hint={"label": "3.000 标高"},
        candidate_index=index,
        llm_runner=runner,
    )
    assert len(pairs) == 2
```

```python
def test_evidence_prefetch_dedupes_same_region_requests():
    batch = prefetch_regions(requests=[req1, req1, req2])
    assert batch.cache_hits >= 1
```

**步骤 2：运行测试验证它失败**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_cross_sheet_locator.py tests/test_evidence_prefetch_service.py -v`
预期：FAIL，提示缺少 `cross_sheet_locator` 或 LLM worker 集成。

**步骤 3：编写最小实现**

```python
class AnchorPair(BaseModel):
    source_sheet_no: str
    target_sheet_no: str
    source_bbox_pct: dict
    target_bbox_pct: dict
    confidence: float

def locate_across_sheets(...):
    candidates = build_cross_sheet_candidates(...)
    return llm_locate_from_candidates(candidates=candidates, llm_runner=...)
```

```python
def prefetch_regions(requests: list[EvidenceRequest]) -> EvidenceBatchResult:
    deduped = _dedupe_by_sheet_and_bbox(requests)
    return _render_and_cache(deduped)
```

**步骤 4：运行测试验证它通过**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_cross_sheet_locator.py tests/test_evidence_prefetch_service.py -v`
预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/cross_sheet_index.py cad-review-backend/services/audit_runtime/cross_sheet_locator.py cad-review-backend/services/audit_runtime/evidence_prefetch_service.py cad-review-backend/services/audit_runtime/evidence_service.py cad-review-backend/services/audit_runtime/hot_sheet_registry.py cad-review-backend/tests/test_cross_sheet_locator.py cad-review-backend/tests/test_evidence_prefetch_service.py
git commit -m "feat: add llm-first locator and evidence prefetch services"
```

### 任务 4：增加主审会话和副审池运行时

**文件：**
- 创建：`cad-review-backend/services/audit_runtime/chief_review_session.py`
- 创建：`cad-review-backend/services/audit_runtime/review_worker_pool.py`
- 创建：`cad-review-backend/services/audit_runtime/review_task_schema.py`
- 创建：`cad-review-backend/tests/test_chief_review_session.py`
- 创建：`cad-review-backend/tests/test_review_worker_pool.py`
- 修改：`cad-review-backend/services/audit_runtime/agent_runner.py`
- 修改：`cad-review-backend/services/audit_runtime/providers/kimi_sdk_provider.py`
- 修改：`cad-review-backend/services/audit_runtime/providers/factory.py`

**步骤 1：编写失败的测试**

```python
def test_chief_review_session_generates_worker_task_cards(monkeypatch):
    session = ChiefReviewSession(...)
    cards = session.plan_worker_tasks(memory=project_memory)
    assert cards[0].worker_kind == "elevation_consistency"
```

```python
def test_review_worker_pool_runs_tasks_in_parallel(monkeypatch):
    pool = ReviewWorkerPool(max_concurrency=4)
    results = pool.run_batch([task1, task2, task3])
    assert len(results) == 3
```

**步骤 2：运行测试验证它失败**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_chief_review_session.py tests/test_review_worker_pool.py -v`
预期：FAIL。

**步骤 3：编写最小实现**

```python
class WorkerTaskCard(BaseModel):
    id: str
    hypothesis_id: str
    worker_kind: str
    objective: str
    source_sheet_no: str
    target_sheet_nos: list[str]
```

```python
class ReviewWorkerPool:
    async def run_batch(self, tasks: list[WorkerTaskCard]) -> list[WorkerResultCard]:
        return await gather_with_limit(tasks, limit=self.max_concurrency)
```

**步骤 4：运行测试验证它通过**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_chief_review_session.py tests/test_review_worker_pool.py -v`
预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/chief_review_session.py cad-review-backend/services/audit_runtime/review_worker_pool.py cad-review-backend/services/audit_runtime/review_task_schema.py cad-review-backend/services/audit_runtime/agent_runner.py cad-review-backend/services/audit_runtime/providers/kimi_sdk_provider.py cad-review-backend/services/audit_runtime/providers/factory.py cad-review-backend/tests/test_chief_review_session.py cad-review-backend/tests/test_review_worker_pool.py
git commit -m "feat: add chief review session and worker pool"
```

### 任务 5：把主流程从旧任务规划切到怀疑卡驱动

**文件：**
- 创建：`cad-review-backend/services/audit_runtime/finding_synthesizer.py`
- 创建：`cad-review-backend/tests/test_finding_synthesizer.py`
- 修改：`cad-review-backend/services/audit_runtime/orchestrator.py`
- 修改：`cad-review-backend/services/master_planner_service.py`
- 修改：`cad-review-backend/services/task_planner_service.py`
- 修改：`cad-review-backend/services/audit_runtime/finding_schema.py`
- 修改：`cad-review-backend/services/audit_runtime/state_transitions.py`
- 修改：`cad-review-backend/services/settings_runtime_summary_service.py`

**步骤 1：编写失败的测试**

```python
def test_orchestrator_uses_chief_review_path_when_feature_flag_enabled(monkeypatch):
    result = run_audit(project_id="proj-chief", audit_version=1)
    assert result["planner"] == "chief_review_agent"
```

```python
def test_finding_synthesizer_merges_worker_cards_into_findings():
    findings = synthesize_findings(worker_results=[...])
    assert findings[0].source_agent == "chief_review_agent"
```

```python
def test_finding_synthesizer_escalates_conflicting_worker_cards_to_chief():
    findings, escalations = synthesize_findings(worker_results=[conflict_a, conflict_b])
    assert findings == []
    assert escalations[0]["escalate_to_chief"] is True
    assert escalations[0]["hypothesis_id"] == conflict_a.hypothesis_id
```

**步骤 2：运行测试验证它失败**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_finding_synthesizer.py tests/test_master_planner_service.py tests/test_audit_runtime_events.py -v`
预期：FAIL。

**步骤 3：编写最小实现**

```python
def synthesize_findings(worker_results: list[WorkerResultCard]) -> tuple[list[Finding], list[dict]]:
    conflicts = detect_conflicts_by_hypothesis(worker_results)
    if conflicts:
        return [], [{"hypothesis_id": item.hypothesis_id, "escalate_to_chief": True} for item in conflicts]
    confirmed = [item for item in worker_results if item.confidence >= 0.8]
    return [to_finding(item) for item in confirmed], []
```

```python
if feature_flags.chief_review_enabled:
    return _run_chief_review_flow(...)
return _run_legacy_flow(...)
```

**步骤 4：运行测试验证它通过**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_finding_synthesizer.py tests/test_master_planner_service.py tests/test_audit_runtime_events.py -v`
预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/finding_synthesizer.py cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/services/master_planner_service.py cad-review-backend/services/task_planner_service.py cad-review-backend/services/audit_runtime/finding_schema.py cad-review-backend/services/audit_runtime/state_transitions.py cad-review-backend/services/settings_runtime_summary_service.py cad-review-backend/tests/test_finding_synthesizer.py
git commit -m "feat: switch orchestration to chief review flow"
```

### 任务 6：把旧专项 Agent 降级成 worker 模板和兼容包装层

**文件：**
- 修改：`cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`cad-review-backend/services/audit/dimension_audit.py`
- 修改：`cad-review-backend/services/audit/material_audit.py`
- 修改：`cad-review-backend/services/audit/index_audit.py`
- 创建：`cad-review-backend/tests/test_chief_review_compatibility_bridge.py`
- 修改：`cad-review-backend/tests/test_relationship_discovery.py`
- 修改：`cad-review-backend/tests/test_dimension_worker_v2.py`
- 修改：`cad-review-backend/tests/test_material_worker_v2.py`

**步骤 1：编写失败的测试**

```python
def test_legacy_dimension_entrypoint_wraps_to_worker_task(monkeypatch):
    payload = run_dimension_audit(...)
    assert payload["compat_mode"] == "worker_wrapper"
```

**步骤 2：运行测试验证它失败**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_chief_review_compatibility_bridge.py tests/test_relationship_discovery.py tests/test_dimension_worker_v2.py tests/test_material_worker_v2.py -v`
预期：FAIL。

**步骤 3：编写最小实现**

```python
def audit_dimensions(...):
    if feature_flags.chief_review_enabled:
        return run_worker_wrapper(worker_kind="dimension_consistency", ...)
    return legacy_dimension_flow(...)
```

**步骤 4：运行测试验证它通过**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_chief_review_compatibility_bridge.py tests/test_relationship_discovery.py tests/test_dimension_worker_v2.py tests/test_material_worker_v2.py -v`
预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit/relationship_discovery.py cad-review-backend/services/audit/dimension_audit.py cad-review-backend/services/audit/material_audit.py cad-review-backend/services/audit/index_audit.py cad-review-backend/tests/test_chief_review_compatibility_bridge.py cad-review-backend/tests/test_relationship_discovery.py cad-review-backend/tests/test_dimension_worker_v2.py cad-review-backend/tests/test_material_worker_v2.py
git commit -m "refactor: wrap legacy audit agents as workers"
```

### 任务 7：前端接入新 Agent 资源和新运行时视图

**文件：**
- 修改：`cad-review-frontend/src/types/api.ts`
- 修改：`cad-review-frontend/src/api/index.ts`
- 修改：`cad-review-frontend/src/pages/SettingsPage.tsx`
- 修改：`cad-review-frontend/src/pages/settings/SettingsPrompts.tsx`
- 创建：`cad-review-frontend/src/pages/settings/SettingsAgentAssets.tsx`
- 修改：`cad-review-frontend/src/pages/settings/SettingsRuntimeSummary.tsx`
- 修改：`cad-review-frontend/src/pages/ProjectDetail.tsx`
- 创建：`cad-review-frontend/src/test/settings-agent-assets.test.tsx`

**步骤 1：编写失败的测试**

```tsx
it('renders chief review assets and runtime lanes', async () => {
  render(<SettingsAgentAssets />);
  expect(await screen.findByText('chief_review')).toBeInTheDocument();
});
```

**步骤 2：运行测试验证它失败**

运行：`cd cad-review-frontend && npm test -- --runInBand`
预期：FAIL，提示页面或类型不存在。

**步骤 3：编写最小实现**

```ts
export interface AgentAssetItem {
  agent_id: string;
  key: 'agent' | 'soul' | 'memory';
  content: string;
}
```

```tsx
<TabsTrigger value="agent-assets">Agent Assets</TabsTrigger>
```

**步骤 4：运行测试验证它通过**

运行：`cd cad-review-frontend && npm test -- --runInBand`
预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-frontend/src/types/api.ts cad-review-frontend/src/api/index.ts cad-review-frontend/src/pages/SettingsPage.tsx cad-review-frontend/src/pages/settings/SettingsPrompts.tsx cad-review-frontend/src/pages/settings/SettingsAgentAssets.tsx cad-review-frontend/src/pages/settings/SettingsRuntimeSummary.tsx cad-review-frontend/src/pages/ProjectDetail.tsx cad-review-frontend/src/test/settings-agent-assets.test.tsx
git commit -m "feat: add frontend support for chief review assets"
```

### 任务 8：影子运行、性能验证和旧路径清理

**文件：**
- 修改：`cad-review-backend/services/audit_runtime/visual_budget.py`
- 修改：`cad-review-backend/services/audit_runtime/runner_broadcasts.py`
- 修改：`cad-review-backend/services/audit_runtime/runner_guardian.py`
- 修改：`cad-review-backend/utils/manual_check_ai_review_flow.py`
- 修改：`cad-review-backend/README.md`
- 修改：`cad-review-frontend/README.md`

**步骤 1：实现影子模式框架**

实现内容：

- 为新旧两条审图路径增加影子运行入口
- 在运行事件里区分 `shadow_legacy` 和 `shadow_chief_review`
- 让 `utils/manual_check_ai_review_flow.py` 新增明确参数：
  - `--run-mode legacy`
  - `--run-mode chief_review`
  - `--run-mode shadow_compare`
- 让 `utils/manual_check_ai_review_flow.py` 支持同项目顺序跑两条路径并汇总结果

**步骤 2：运行人工影子验收**

运行：

```bash
cd cad-review-backend
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id proj-shadow --start-audit --wait-seconds 45 --provider-mode kimi_sdk --run-mode legacy
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id proj-shadow --start-audit --wait-seconds 45 --provider-mode kimi_sdk --run-mode chief_review
```

人工记录：

- 旧路径总耗时
- 新路径总耗时
- finding 重叠率
- chief 路径新增 / 丢失的问题条数
- 运行过程中是否出现明显卡死、空转、异常恢复

**步骤 3：把人工验收结果写进 README**

写入内容：

- `proj-shadow` 的新旧路径耗时对比
- finding 重叠率
- 差异解释
- 是否允许进入主流程切换

**步骤 4：提交**

```bash
git add cad-review-backend/services/audit_runtime/visual_budget.py cad-review-backend/services/audit_runtime/runner_broadcasts.py cad-review-backend/services/audit_runtime/runner_guardian.py cad-review-backend/utils/manual_check_ai_review_flow.py cad-review-backend/README.md cad-review-frontend/README.md
git commit -m "chore: validate and document chief review rollout"
```

## 执行顺序建议

1. 先做任务 1 和任务 2，先把 Agent 资源和 ProjectMemory 立起来。
2. 再做任务 3 和任务 4，让主审和副审群跑得起来。
3. 再先做任务 8 的影子运行部分，搭影子模式框架，并用 `proj-shadow` 做人工验收。
4. 影子验证通过后，再做任务 5 和任务 6，把主流程切过去，同时保留兼容包装层。
5. 最后做任务 7，补前端和最终清理。

## 验收标准

- 新系统存在真实常驻 `chief_review_agent` 会话
- 主审可按项目复杂度动态生成副审
- `relationship / dimension / material` 不再是一级业务 Agent
- `AGENTS / SOUL / MEMORY` 成为主资源，`PROMPT` 只负责组装
- LLM 主导问题发现、图纸语义建图、跨图定位，JSON 只做候选锚点和验证
- 在中等复杂项目上，并行 worker 模式比“主审和导航对话式串行流程”更快
