# 副审能力 Skill 化实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 把适合下沉的副审能力从“硬编码 agent 逻辑”重构成“Runtime + Skill”两层结构，先完成 `index_reference` 和 `material_semantic_consistency` 两个领域的 skill 化。

**架构：** 保留现有 `chief_review / runner / worker_pool / project_memory / event` 运行时骨架，不把强状态系统塞进 skill。新增一层 `review worker skill` 合同，把领域规则、证据偏好、升级条件、输出约束收进 skill 资源；`review_worker_runtime.py` 只负责调度、上下文注入、调用 skill 执行器和兜底。第一阶段只迁移边界最清楚的两个领域，`dimension / relationship` 暂不一起动。

**技术栈：** Python / FastAPI / SQLAlchemy / pytest / 现有 audit_runtime / 现有 agents 资源目录

---

### 任务 1：建立副审 Skill 合同和资源加载层

**文件：**
- 创建：`cad-review-backend/agents/review_worker/skills/index_reference/SKILL.md`
- 创建：`cad-review-backend/agents/review_worker/skills/material_semantic_consistency/SKILL.md`
- 创建：`cad-review-backend/services/audit_runtime/worker_skill_loader.py`
- 创建：`cad-review-backend/tests/test_worker_skill_loader.py`
- 修改：`cad-review-backend/agents/review_worker/AGENTS.md`

**步骤 1：编写失败的测试**

```python
def test_worker_skill_loader_reads_skill_markdown():
    bundle = load_worker_skill("index_reference")
    assert bundle.worker_kind == "index_reference"
    assert "输出必须是 JSON" in bundle.skill_markdown


def test_worker_skill_loader_rejects_unknown_worker_kind():
    with pytest.raises(FileNotFoundError):
        load_worker_skill("unknown_worker")
```

**步骤 2：运行测试验证它失败**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_worker_skill_loader.py -v`
预期：FAIL，提示 `load_worker_skill` 不存在或 skill 目录不存在。

**步骤 3：编写最小实现**

```python
@dataclass(frozen=True)
class WorkerSkillBundle:
    worker_kind: str
    skill_markdown: str
    skill_path: Path


def load_worker_skill(worker_kind: str) -> WorkerSkillBundle:
    skill_path = SKILLS_ROOT / worker_kind / "SKILL.md"
    if not skill_path.exists():
        raise FileNotFoundError(worker_kind)
    return WorkerSkillBundle(
        worker_kind=worker_kind,
        skill_markdown=skill_path.read_text(encoding="utf-8"),
        skill_path=skill_path,
    )
```

说明：
- 第一阶段 `WorkerSkillBundle` 先只保留 `worker_kind / skill_markdown / skill_path`
- `skill_version` 不在这一轮实现，放到第二阶段补齐

**步骤 4：运行测试验证它通过**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_worker_skill_loader.py -v`
预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/agents/review_worker/AGENTS.md cad-review-backend/agents/review_worker/skills cad-review-backend/services/audit_runtime/worker_skill_loader.py cad-review-backend/tests/test_worker_skill_loader.py
git commit -m "feat: add review worker skill loader"
```

### 任务 2：给副审 Skill 定义统一执行合同

**文件：**
- 创建：`cad-review-backend/services/audit_runtime/worker_skill_contract.py`
- 创建：`cad-review-backend/services/audit_runtime/worker_skill_registry.py`
- 创建：`cad-review-backend/tests/test_worker_skill_registry.py`
- 修改：`cad-review-backend/services/audit_runtime/review_worker_runtime.py`

**步骤 1：编写失败的测试**

```python
def test_worker_skill_registry_returns_executor_for_index_reference():
    executor = get_worker_skill_executor("index_reference")
    assert executor.worker_kind == "index_reference"


def test_native_review_worker_prefers_registered_skill_executor(monkeypatch):
    monkeypatch.setattr(
        "services.audit_runtime.review_worker_runtime.get_worker_skill_executor",
        lambda worker_kind: FakeExecutor(worker_kind="index_reference"),
    )
    result = asyncio.run(run_native_review_worker(task=task, db=db))
    assert result.meta["skill_mode"] == "worker_skill"
```

**步骤 2：运行测试验证它失败**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_worker_skill_registry.py -v`
预期：FAIL，提示缺少 `get_worker_skill_executor` 或 `skill_mode`。

**步骤 3：编写最小实现**

```python
@dataclass(frozen=True)
class WorkerSkillExecutor:
    worker_kind: str
    execute: Callable[..., Awaitable[WorkerResultCard]]


def get_worker_skill_executor(worker_kind: str) -> WorkerSkillExecutor | None:
    return _REGISTRY.get(worker_kind)
```

```python
async def run_native_review_worker(*, task: WorkerTaskCard, db) -> WorkerResultCard | None:
    skill_executor = get_worker_skill_executor(task.worker_kind)
    if skill_executor is not None:
        return await skill_executor.execute(task=task, db=db)
    ...
```

**步骤 4：运行测试验证它通过**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_worker_skill_registry.py -v`
预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/worker_skill_contract.py cad-review-backend/services/audit_runtime/worker_skill_registry.py cad-review-backend/services/audit_runtime/review_worker_runtime.py cad-review-backend/tests/test_worker_skill_registry.py
git commit -m "feat: add worker skill execution contract"
```

### 任务 3：把 `index_reference` 下沉成第一个真正的 Worker Skill

**文件：**
- 创建：`cad-review-backend/services/audit_runtime/worker_skills/index_reference_skill.py`
- 创建：`cad-review-backend/tests/test_index_reference_skill.py`
- 修改：`cad-review-backend/services/audit_runtime/worker_skill_registry.py`
- 修改：`cad-review-backend/services/audit_runtime/review_worker_runtime.py`
- 修改：`cad-review-backend/agents/review_worker/skills/index_reference/SKILL.md`

**步骤 1：编写失败的测试**

```python
def test_index_reference_skill_uses_skill_bundle_and_returns_worker_result(monkeypatch):
    result = asyncio.run(run_index_reference_skill(task=task, db=db))
    assert result.meta["skill_mode"] == "worker_skill"
    assert result.meta["skill_id"] == "index_reference"
```

```python
def test_index_reference_skill_reuses_existing_candidate_collection(monkeypatch):
    monkeypatch.setattr(index_skill, "_collect_index_issue_candidates", lambda *args, **kwargs: [...])
    result = asyncio.run(run_index_reference_skill(task=task, db=db))
    assert result.status in {"confirmed", "needs_review", "rejected"}
```

**步骤 2：运行测试验证它失败**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_index_reference_skill.py -v`
预期：FAIL，提示缺少 `run_index_reference_skill`。

**步骤 3：编写最小实现**

```python
async def run_index_reference_skill(*, task: WorkerTaskCard, db) -> WorkerResultCard:
    skill = load_worker_skill("index_reference")
    candidates = _collect_index_issue_candidates(...)
    reviewed = await _review_index_issue_candidates_async(...)
    return WorkerResultCard(
        ...,
        meta={
            "skill_mode": "worker_skill",
            "skill_id": "index_reference",
            "skill_path": str(skill.skill_path),
        },
    )
```

实现约束：
- `_collect_index_issue_candidates` 保留在原始 `index_audit.py` 模块
- `index_reference_skill.py` 只能通过 `import` 复用旧候选收集函数，不允许复制一份实现
- `test_index_worker_ai_review.py` 继续覆盖原始候选收集逻辑，避免 skill 化后出现两份实现各自漂移

**步骤 4：运行测试验证它通过**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_index_reference_skill.py tests/test_index_worker_ai_review.py tests/test_chief_review_compatibility_bridge.py -v`
预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/worker_skills/index_reference_skill.py cad-review-backend/services/audit_runtime/worker_skill_registry.py cad-review-backend/services/audit_runtime/review_worker_runtime.py cad-review-backend/agents/review_worker/skills/index_reference/SKILL.md cad-review-backend/tests/test_index_reference_skill.py
git commit -m "feat: skillize index review worker"
```

### 任务 4：把 `material_semantic_consistency` 下沉成第二个 Worker Skill

**文件：**
- 创建：`cad-review-backend/services/audit_runtime/worker_skills/material_semantic_skill.py`
- 创建：`cad-review-backend/tests/test_material_semantic_skill.py`
- 修改：`cad-review-backend/services/audit_runtime/worker_skill_registry.py`
- 修改：`cad-review-backend/services/audit_runtime/review_worker_runtime.py`
- 修改：`cad-review-backend/agents/review_worker/skills/material_semantic_consistency/SKILL.md`

**步骤 1：编写失败的测试**

```python
def test_material_skill_returns_worker_skill_metadata(monkeypatch):
    result = asyncio.run(run_material_semantic_skill(task=task, db=db))
    assert result.meta["skill_mode"] == "worker_skill"
    assert result.meta["skill_id"] == "material_semantic_consistency"
```

```python
def test_material_skill_reuses_filtered_candidate_collection(monkeypatch):
    monkeypatch.setattr(material_skill, "_collect_material_issue_candidates", lambda *args, **kwargs: [...])
    result = asyncio.run(run_material_semantic_skill(task=task, db=db))
    assert result.summary
```

**步骤 2：运行测试验证它失败**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_material_semantic_skill.py -v`
预期：FAIL，提示缺少 `run_material_semantic_skill`。

**步骤 3：编写最小实现**

```python
async def run_material_semantic_skill(*, task: WorkerTaskCard, db) -> WorkerResultCard:
    skill = load_worker_skill("material_semantic_consistency")
    candidates = collect_material_issue_candidates(...)
    reviewed = await review_material_candidates_async(...)
    return WorkerResultCard(
        ...,
        meta={
            "skill_mode": "worker_skill",
            "skill_id": "material_semantic_consistency",
            "skill_path": str(skill.skill_path),
        },
    )
```

**步骤 4：运行测试验证它通过**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_material_semantic_skill.py tests/test_material_worker_v2.py tests/test_chief_review_compatibility_bridge.py -v`
预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/worker_skills/material_semantic_skill.py cad-review-backend/services/audit_runtime/worker_skill_registry.py cad-review-backend/services/audit_runtime/review_worker_runtime.py cad-review-backend/agents/review_worker/skills/material_semantic_consistency/SKILL.md cad-review-backend/tests/test_material_semantic_skill.py
git commit -m "feat: skillize material review worker"
```

### 任务 5：把主审侧调度和验收说明切到 Skill 视角

**文件：**
- 修改：`cad-review-backend/services/audit_runtime/chief_review_session.py`
- 修改：`cad-review-backend/services/audit_runtime/review_task_schema.py`
- 修改：`cad-review-backend/services/audit_runtime/finding_synthesizer.py`
- 修改：`cad-review-backend/README.md`
- 创建：`cad-review-backend/tests/test_worker_skill_dispatch.py`

**步骤 1：编写失败的测试**

```python
def test_chief_session_marks_skillized_worker_tasks():
    tasks = chief_session.plan_worker_tasks(memory=memory)
    index_task = next(task for task in tasks if task.worker_kind == "index_reference")
    assert index_task.context["execution_mode"] == "worker_skill"
```

```python
def test_finding_synthesizer_preserves_skill_metadata():
    findings, escalations = synthesize_findings(worker_results=[...])
    assert findings[0].meta["skill_id"] == "index_reference"
```

**步骤 2：运行测试验证它失败**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_worker_skill_dispatch.py -v`
预期：FAIL，提示 `execution_mode` 或 `skill_id` 未透传。

**步骤 3：编写最小实现**

```python
WorkerTaskCard(
    ...,
    context={
        ...,
        "execution_mode": "worker_skill",
        "skill_id": worker_kind,
    },
)
```

```python
finding.meta.update(
    {
        "execution_mode": worker_result.meta.get("skill_mode"),
        "skill_id": worker_result.meta.get("skill_id"),
    }
)
```

**步骤 4：运行测试验证它通过**

运行：`cd cad-review-backend && ./venv/bin/pytest tests/test_worker_skill_dispatch.py tests/test_chief_review_session.py tests/test_finding_synthesizer.py -v`
预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/chief_review_session.py cad-review-backend/services/audit_runtime/review_task_schema.py cad-review-backend/services/audit_runtime/finding_synthesizer.py cad-review-backend/README.md cad-review-backend/tests/test_worker_skill_dispatch.py
git commit -m "feat: wire chief review to worker skills"
```

### 任务 6：冻结边界并记录第二阶段迁移清单

**文件：**
- 修改：`docs/plans/2026-03-11-review-worker-skillization-implementation-plan.md`
- 创建：`docs/plans/2026-03-11-review-worker-skillization-phase-2.md`

**步骤 1：补阶段结论**

把本阶段明确写死：
- 已 skill 化：`index_reference`、`material_semantic_consistency`
- 暂不迁移：`node_host_binding`、`elevation_consistency`、`spatial_consistency`
- 不改：`chief_review` 会话、`runner`、`observer`、`project_memory` 的系统角色

**步骤 2：记录第二阶段风险**

```markdown
- `relationship` 依赖跨图 discovery，多轮证据与子会话恢复耦合更深
- `dimension` 依赖单图语义 + pair compare + provider 节流，先不一起动
- 第二阶段前置条件：真实项目 `test1` 在 skill 化后能稳定跑出一轮结果
- 第二阶段前置条件：`WorkerSkillBundle` 补 `skill_version` 字段，供运行日志和问题追踪使用
```

**步骤 3：手工检查文档**

运行：`rg -n "skill 化|index_reference|material_semantic_consistency|第二阶段" docs/plans/2026-03-11-review-worker-skillization-implementation-plan.md docs/plans/2026-03-11-review-worker-skillization-phase-2.md`
预期：能看到边界、已做、未做三类说明。

**步骤 4：提交**

```bash
git add docs/plans/2026-03-11-review-worker-skillization-implementation-plan.md docs/plans/2026-03-11-review-worker-skillization-phase-2.md
git commit -m "docs: record worker skillization boundaries"
```

---

## 边界说明

本计划明确：
- 做：把稳定、可复用、输入输出清楚的副审领域能力抽成 skill
- 不做：把 `chief_review / runner / observer / recovery / event bus` 这些运行时系统抽成 skill
- 不做：这一轮直接迁移 `relationship / dimension`
- 不做：为了 skill 化去重写现有落库、恢复、限流系统

## 第一阶段冻结结果

- 已 skill 化：`index_reference`、`material_semantic_consistency`
- 暂不迁移：`node_host_binding`、`elevation_consistency`、`spatial_consistency`
- 不改：`chief_review` 会话、`runner`、`observer`、`project_memory` 的系统角色
- 第二阶段前置条件：真实项目 `test1` 在 skill 化后能稳定跑出一轮结果
- 第二阶段前置条件：`WorkerSkillBundle` 补 `skill_version` 字段，供运行日志和问题追踪使用

## 执行顺序建议

1. 先只做任务 1-2，确认合同和目录结构稳。
2. 再做任务 3-4，把两个最稳的领域迁进去。
3. 最后做任务 5-6，把主审透传和边界文档补齐。
