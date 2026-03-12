# 新架构切换与旧架构退役实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

> **执行前置：** 先执行 `cd /Users/harry/@dev/ccad`，以下路径默认相对仓库根目录。

**目标：** 让审图主流程真正由 `chief_review + review_worker + Agent/Skill` 驱动，旧 `stage prompt + legacy pipeline` 逐步降级、下线、删除。

**架构：** 保留现有运行时、事件流、限流、恢复和报告层，把“模型到底吃什么内容、谁负责做判断”从旧 `ai_prompt_service + stage_key` 迁到 `AGENTS.md / SOUL.md / MEMORY.md / SKILL.md`。迁移采用“样板链路先行、领域逐个切换、旧链路只做兼容回退”的方式，直到 `chief_review` 成为默认且唯一业务主路。

**技术栈：** Python / FastAPI / SQLAlchemy / pytest / React / Vite / OpenRouter/Kimi 兼容通道 / 现有 audit_runtime 事件流

---

## 任务边界

这份计划要做：

- 让主审和副审真正消费 Agent/Skill 资源
- 把旧 `stage prompt` 降级成模板兼容层
- 逐个把 `index / material / relationship / dimension` 收编进新架构
- 给迁移过程加上可观测性，能判断一轮 run 到底吃的是新脑子还是旧脑子
- 在验证稳定后删除旧 `legacy/v2` 业务主路

这份计划暂时不做：

- 不更换数据库
- 不重写报告导出格式
- 不重写前端除“兼容入口提示”外的大块交互
- 不修改 CI/CD、生产密钥、外部 provider 计费策略

## 迁移原则

1. 新资源先变成运行时真入口，再删旧入口。
2. 先迁“判断脑子”，后迁“模板壳子”。
3. 每迁完一个领域，都能从事件和结果里证明它已经不再吃旧 `stage prompt`。
4. 旧链路不允许无限期共存；每个兼容入口都要有明确删除条件。

### 任务 1：建立“运行时提示词来源”总装配层

**文件：**
- 创建：`cad-review-backend/services/audit_runtime/runtime_prompt_assembler.py`
- 创建：`cad-review-backend/tests/test_runtime_prompt_assembler.py`
- 修改：`cad-review-backend/services/ai_prompt_service.py`
- 修改：`cad-review-backend/services/audit_runtime/worker_skill_loader.py`
- 修改：`cad-review-backend/services/audit_runtime/worker_skill_contract.py`

**步骤 1：编写失败的测试**

```python
def test_assemble_worker_prompt_merges_agent_soul_memory_and_skill():
    prompt = assemble_worker_runtime_prompt(
        worker_kind="index_reference",
        task_context={"source_sheet_no": "A1-01"},
    )
    assert "Review Worker Agent" in prompt.system_prompt
    assert "Index Reference Worker Skill" in prompt.system_prompt
    assert prompt.meta["prompt_source"] == "agent_skill"
```

```python
def test_assemble_legacy_template_prompt_marks_compat_mode():
    prompt = assemble_legacy_stage_prompt(
        stage_key="index_visual_review",
        variables={"source_sheet_no": "A1-01"},
    )
    assert prompt.meta["prompt_source"] == "legacy_stage_template"
```

**步骤 2：运行测试验证它失败**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_runtime_prompt_assembler.py -v`

预期：FAIL，提示 `assemble_worker_runtime_prompt` 或 `assemble_legacy_stage_prompt` 不存在。

**步骤 3：编写最小实现**

```python
@dataclass(frozen=True)
class RuntimePromptBundle:
    system_prompt: str
    user_prompt: str
    meta: dict[str, Any]


def assemble_worker_runtime_prompt(*, worker_kind: str, task_context: dict[str, Any]) -> RuntimePromptBundle:
    agent = build_agent_runtime_prompt("review_worker")
    skill = load_worker_skill(worker_kind)
    return RuntimePromptBundle(
        system_prompt=f"{agent}\n\n{skill.skill_markdown}",
        user_prompt=json.dumps(task_context, ensure_ascii=False),
        meta={"prompt_source": "agent_skill", "worker_kind": worker_kind},
    )
```

**步骤 4：运行测试验证它通过**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_runtime_prompt_assembler.py -v`

预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/runtime_prompt_assembler.py cad-review-backend/tests/test_runtime_prompt_assembler.py cad-review-backend/services/ai_prompt_service.py cad-review-backend/services/audit_runtime/worker_skill_loader.py cad-review-backend/services/audit_runtime/worker_skill_contract.py
git commit -m "feat: add runtime prompt assembler for agent skill prompts"
```

### 任务 2：让主审真正消费 `chief_review` 资源，而不是只靠默认启发式

**文件：**
- 创建：`cad-review-backend/services/audit_runtime/chief_review_planner.py`
- 创建：`cad-review-backend/tests/test_chief_review_planner.py`
- 修改：`cad-review-backend/services/audit_runtime/orchestrator.py`
- 修改：`cad-review-backend/services/audit_runtime/chief_review_session.py`
- 修改：`cad-review-backend/services/chief_review_memory_service.py`

**步骤 1：编写失败的测试**

```python
def test_chief_review_planner_uses_agent_runtime_prompt(monkeypatch):
    bundle = plan_chief_review_hypotheses(project_id="p1", audit_version=1, memory={"confirmed_links": []}, db=None)
    assert bundle.meta["prompt_source"] == "chief_agent"
```

```python
def test_chief_review_session_prefers_planner_hypotheses_over_default_edges():
    session = ChiefReviewSession(project_id="p1", audit_version=1)
    tasks = session.plan_worker_tasks(
        memory={"active_hypotheses": [{"id": "h1", "topic": "索引引用", "objective": "核对A1-01", "source_sheet_no": "A1-01", "target_sheet_nos": ["A4-01"]}]}
    )
    assert tasks[0].worker_kind == "index_reference"
```

**步骤 2：运行测试验证它失败**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_chief_review_planner.py tests/test_chief_review_session.py -v`

预期：FAIL。

**步骤 3：编写最小实现**

```python
def plan_chief_review_hypotheses(...):
    prompt = assemble_chief_runtime_prompt(...)
    turn = runner.run_once(...)
    hypotheses = normalize_hypotheses(turn.output)
    return {"items": hypotheses, "meta": {"prompt_source": "chief_agent"}}
```

```python
memory = save_project_memory(
    db,
    project_id=project_id,
    audit_version=audit_version,
    payload={**memory, "active_hypotheses": planner_result["items"]},
)
```

**步骤 4：运行测试验证它通过**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_chief_review_planner.py tests/test_chief_review_session.py tests/test_chief_review_orchestrator.py -v`

预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/chief_review_planner.py cad-review-backend/tests/test_chief_review_planner.py cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/services/audit_runtime/chief_review_session.py cad-review-backend/services/chief_review_memory_service.py
git commit -m "feat: drive chief review with chief agent resources"
```

### 任务 3：把 `index_reference` 彻底迁成 Agent/Skill 驱动样板链路

**文件：**
- 修改：`cad-review-backend/services/audit_runtime/worker_skills/index_reference_skill.py`
- 修改：`cad-review-backend/services/audit/index_audit.py`
- 修改：`cad-review-backend/services/audit_runtime/review_worker_runtime.py`
- 修改：`cad-review-backend/tests/test_index_reference_skill.py`
- 修改：`cad-review-backend/tests/test_worker_skill_dispatch.py`

**步骤 1：编写失败的测试**

```python
def test_index_reference_skill_uses_agent_skill_prompt_not_stage_prompt(monkeypatch):
    captured = {}
    monkeypatch.setattr(index_skill, "assemble_worker_runtime_prompt", lambda **kwargs: captured.setdefault("source", "agent_skill"))
    run = asyncio.run(run_index_reference_skill(task=task, db=db))
    assert captured["source"] == "agent_skill"
```

```python
def test_index_reference_skill_result_marks_prompt_source():
    result = asyncio.run(run_index_reference_skill(task=task, db=db))
    assert result.meta["prompt_source"] == "agent_skill"
```

**步骤 2：运行测试验证它失败**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_index_reference_skill.py tests/test_worker_skill_dispatch.py -v`

预期：FAIL。

**步骤 3：编写最小实现**

```python
prompt_bundle = assemble_worker_runtime_prompt(worker_kind="index_reference", task_context=payload)
turn = await runner.run_stream(
    RunnerTurnRequest(
        system_prompt=prompt_bundle.system_prompt,
        user_prompt=prompt_bundle.user_prompt,
        ...
    )
)
meta["prompt_source"] = prompt_bundle.meta["prompt_source"]
```

**步骤 4：运行测试验证它通过**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_index_reference_skill.py tests/test_worker_skill_dispatch.py tests/test_chief_review_compatibility_bridge.py -v`

预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/worker_skills/index_reference_skill.py cad-review-backend/services/audit/index_audit.py cad-review-backend/services/audit_runtime/review_worker_runtime.py cad-review-backend/tests/test_index_reference_skill.py cad-review-backend/tests/test_worker_skill_dispatch.py
git commit -m "feat: migrate index worker to agent skill prompt pipeline"
```

### 任务 4：把 `material_semantic_consistency` 迁成同样的样板链路

**文件：**
- 修改：`cad-review-backend/services/audit_runtime/worker_skills/material_semantic_skill.py`
- 修改：`cad-review-backend/services/audit/material_audit.py`
- 修改：`cad-review-backend/tests/test_material_semantic_skill.py`
- 修改：`cad-review-backend/tests/test_material_worker_v2.py`

**步骤 1：编写失败的测试**

```python
def test_material_skill_uses_agent_skill_prompt():
    result = asyncio.run(run_material_semantic_skill(task=task, db=db))
    assert result.meta["prompt_source"] == "agent_skill"
```

**步骤 2：运行测试验证它失败**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_material_semantic_skill.py tests/test_material_worker_v2.py -v`

预期：FAIL。

**步骤 3：编写最小实现**

```python
prompt_bundle = assemble_worker_runtime_prompt(
    worker_kind="material_semantic_consistency",
    task_context={"sheet_no": task.source_sheet_no, "rule_issues": compact_rule_issues},
)
```

**步骤 4：运行测试验证它通过**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_material_semantic_skill.py tests/test_material_worker_v2.py tests/test_worker_skill_dispatch.py -v`

预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/worker_skills/material_semantic_skill.py cad-review-backend/services/audit/material_audit.py cad-review-backend/tests/test_material_semantic_skill.py cad-review-backend/tests/test_material_worker_v2.py
git commit -m "feat: migrate material worker to agent skill prompt pipeline"
```

### 任务 5：把 `node_host_binding / relationship` 从旧 `sheet_relationship_discovery` 收编进副审 Skill

**文件：**
- 创建：`cad-review-backend/services/audit_runtime/worker_skills/node_host_binding_skill.py`
- 修改：`cad-review-backend/services/audit_runtime/worker_skill_registry.py`
- 修改：`cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`cad-review-backend/services/audit_runtime/review_worker_runtime.py`
- 创建：`cad-review-backend/tests/test_node_host_binding_skill.py`

**步骤 1：编写失败的测试**

```python
def test_node_host_binding_skill_uses_agent_skill_prompt():
    result = asyncio.run(run_node_host_binding_skill(task=task, db=db))
    assert result.meta["prompt_source"] == "agent_skill"
```

**步骤 2：运行测试验证它失败**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_node_host_binding_skill.py tests/test_relationship_worker_v2.py -v`

预期：FAIL。

**步骤 3：编写最小实现**

```python
def register_worker_skill(worker_kind: str, execute: WorkerSkillCallable) -> None:
    _CALLABLE_REGISTRY[worker_kind] = execute
```

```python
register_worker_skill("node_host_binding", run_node_host_binding_skill)
prompt_bundle = assemble_worker_runtime_prompt(worker_kind="node_host_binding", task_context=payload)
```

**步骤 4：运行测试验证它通过**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_node_host_binding_skill.py tests/test_relationship_worker_v2.py tests/test_chief_review_compatibility_bridge.py -v`

预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/worker_skills/node_host_binding_skill.py cad-review-backend/services/audit_runtime/worker_skill_registry.py cad-review-backend/services/audit/relationship_discovery.py cad-review-backend/services/audit_runtime/review_worker_runtime.py cad-review-backend/tests/test_node_host_binding_skill.py
git commit -m "feat: migrate node host binding into worker skill runtime"
```

### 任务 6：最后收最重的 `dimension / elevation / spatial`

**文件：**
- 创建：`cad-review-backend/services/audit_runtime/worker_skills/dimension_consistency_skill.py`
- 修改：`cad-review-backend/services/audit_runtime/worker_skill_registry.py`
- 修改：`cad-review-backend/services/audit/dimension_audit.py`
- 修改：`cad-review-backend/services/audit_runtime/review_worker_runtime.py`
- 修改：`cad-review-backend/tests/test_dimension_worker_v2.py`
- 创建：`cad-review-backend/tests/test_dimension_consistency_skill.py`

**步骤 1：编写失败的测试**

```python
def test_dimension_skill_uses_agent_skill_prompt():
    result = asyncio.run(run_dimension_consistency_skill(task=task, db=db))
    assert result.meta["prompt_source"] == "agent_skill"
```

```python
def test_dimension_skill_keeps_singleflight_and_gate():
    result = asyncio.run(run_dimension_consistency_skill(task=task, db=db))
    assert result.meta["worker_kind"] in {"elevation_consistency", "spatial_consistency"}
```

**步骤 2：运行测试验证它失败**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_dimension_consistency_skill.py tests/test_dimension_worker_v2.py -v`

预期：FAIL。

**步骤 3：编写最小实现**

```python
for worker_kind in ("elevation_consistency", "spatial_consistency"):
    register_dimension_executor(worker_kind, run_dimension_consistency_skill)
```

```python
prompt_bundle = assemble_worker_runtime_prompt(worker_kind=task.worker_kind, task_context=payload)
```

**步骤 4：运行测试验证它通过**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_dimension_consistency_skill.py tests/test_dimension_worker_v2.py tests/test_llm_request_gate.py tests/test_agent_runner_sessions.py -v`

预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/worker_skills/dimension_consistency_skill.py cad-review-backend/services/audit_runtime/worker_skill_registry.py cad-review-backend/services/audit/dimension_audit.py cad-review-backend/services/audit_runtime/review_worker_runtime.py cad-review-backend/tests/test_dimension_consistency_skill.py cad-review-backend/tests/test_dimension_worker_v2.py
git commit -m "feat: migrate dimension family into worker skill runtime"
```

### 任务 7：把旧 `ai_prompt_service` 降级成兼容模板层

**文件：**
- 修改：`cad-review-backend/services/ai_prompt_service.py`
- 修改：`cad-review-backend/services/skill_pack_service.py`
- 修改：`cad-review-backend/routers/settings.py`
- 创建：`cad-review-backend/tests/test_legacy_prompt_compatibility.py`
- 修改：`cad-review-backend/README.md`

**步骤 1：编写失败的测试**

```python
def test_legacy_stage_prompt_is_marked_template_only():
    payload = list_prompt_stages()["items"]
    target = next(item for item in payload if item["stage_key"] == "index_visual_review")
    assert target["lifecycle"] == "template_only"
```

```python
def test_resolve_stage_system_prompt_with_skills_warns_template_only(monkeypatch):
    prompts = resolve_stage_prompts("index_visual_review", {"source_sheet_no": "A1-01"})
    assert prompts["meta"]["prompt_source"] == "legacy_stage_template"
```

**步骤 2：运行测试验证它失败**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_legacy_prompt_compatibility.py -v`

预期：FAIL。

**步骤 3：编写最小实现**

```python
PromptStageDefinition(..., lifecycle="template_only", replacement="review_worker.skills.index_reference")
```

```python
return {
    "system_prompt": rendered_system,
    "user_prompt": rendered_user,
    "meta": {"prompt_source": "legacy_stage_template", "stage_key": stage_key},
}
```

**步骤 4：运行测试验证它通过**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_legacy_prompt_compatibility.py tests/test_runtime_prompt_assembler.py -v`

预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/ai_prompt_service.py cad-review-backend/services/skill_pack_service.py cad-review-backend/routers/settings.py cad-review-backend/tests/test_legacy_prompt_compatibility.py cad-review-backend/README.md
git commit -m "refactor: demote legacy stage prompts to template compatibility layer"
```

### 任务 8：让 `legacy / v2` 主路退出，只保留新主路

**文件：**
- 修改：`cad-review-backend/services/audit_runtime/orchestrator.py`
- 修改：`cad-review-backend/services/audit_runtime_service.py`
- 修改：`cad-review-backend/routers/audit.py`
- 创建：`cad-review-backend/tests/test_pipeline_mode_cutover.py`
- 修改：`cad-review-frontend/src/pages/settings/SettingsLegacyStagePrompts.tsx`

**步骤 1：编写失败的测试**

```python
def test_start_audit_defaults_to_chief_review_pipeline():
    payload = start_audit(...)
    assert payload["pipeline_mode"] == "chief_review"
```

```python
def test_legacy_pipeline_requires_explicit_override():
    assert _resolve_pipeline_mode(env={"AUDIT_LEGACY_PIPELINE_ALLOWED": "0"}) == "chief_review"
```

**步骤 2：运行测试验证它失败**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_pipeline_mode_cutover.py tests/test_start_audit_api.py -v`

预期：FAIL。

**步骤 3：编写最小实现**

```python
def _resolve_pipeline_mode(...):
    if str(os.getenv("AUDIT_LEGACY_PIPELINE_ALLOWED", "0")).strip() not in {"1", "true"}:
        return "chief_review"
```

**步骤 4：运行测试验证它通过**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_pipeline_mode_cutover.py tests/test_start_audit_api.py tests/test_chief_review_orchestrator.py -v`

预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/services/audit_runtime_service.py cad-review-backend/routers/audit.py cad-review-backend/tests/test_pipeline_mode_cutover.py cad-review-frontend/src/pages/settings/SettingsLegacyStagePrompts.tsx
git commit -m "refactor: make chief review the only default pipeline"
```

**任务 8.5：真实项目切主路验收门槛**

**文件：**
- 创建：`docs/plans/2026-03-12-chief-review-cutover-gate-report.md`

**步骤 1：运行真实项目验收**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/python utils/manual_check_ai_review_flow.py \
  --project-id proj_20260309231506_001af8d5 \
  --base-url http://127.0.0.1:7002 \
  --provider-mode api \
  --run-mode chief_review
```

**步骤 2：记录必须通过的门槛**

验收报告里必须同时满足：

- 事件里出现 `chief_review_agent`
- 至少有 1 个副审任务真正执行
- 副审结果元数据里出现 `prompt_source=agent_skill`
- 不再出现“业务主判断依赖旧 `stage_key`”的运行时证据

**步骤 3：保存验收结论**

把结果写入：

`docs/plans/2026-03-12-chief-review-cutover-gate-report.md`

**步骤 4：只有门槛通过，才能继续任务 9**

如果门槛没过：

- 停在任务 8.5
- 不删旧代码
- 先补修复，再重跑验收

### 任务 9：删除兼容死代码并做最终验证

**文件：**
- 删除：确认不再被引用的旧 `legacy/v2` 业务分支函数与测试夹具
- 修改：`cad-review-backend/README.md`
- 修改：`cad-review-frontend/README.md`
- 创建：`docs/plans/2026-03-12-new-architecture-cutover-validation-report.md`

**步骤 1：编写失败的测试**

```python
def test_repo_has_no_runtime_imports_of_legacy_stage_prompts():
    matches = scan_repo_for_runtime_legacy_stage_prompt_usage()
    assert matches == []
```

**步骤 2：运行测试验证它失败**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest tests/test_legacy_prompt_compatibility.py::test_repo_has_no_runtime_imports_of_legacy_stage_prompts -v`

预期：FAIL。

**步骤 3：编写最小实现**

```python
def scan_repo_for_runtime_legacy_stage_prompt_usage():
    blocked = ["resolve_stage_system_prompt_with_skills(", "resolve_stage_prompts("]
    ...
```

删除所有已经被新装配层取代的运行时引用，只保留模板兼容入口和设置页展示入口。

**步骤 4：运行测试验证它通过**

运行：`cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q`

预期：PASS。

然后运行真实项目回归：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/python utils/manual_check_ai_review_flow.py \
  --project-id proj_20260309231506_001af8d5 \
  --base-url http://127.0.0.1:7002 \
  --provider-mode api \
  --run-mode chief_review
```

预期：
- 事件里出现 `chief_review_agent`
- 副审结果里 `prompt_source=agent_skill`
- 不再出现把业务主判断建立在旧 `stage_key` 上的事件/元数据

**步骤 5：提交**

```bash
git add -p cad-review-backend
git add -p cad-review-frontend
git add docs/plans/2026-03-12-new-architecture-cutover-validation-report.md
git commit -m "refactor: remove legacy pipeline after chief review cutover"
```
