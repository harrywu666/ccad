# AI 审图总控架构实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 将当前固定图片套餐驱动的 AI 审图流程，渐进迁移为“总控调度 + 证据规划 + 统一证据服务 + 专用审查器 + 用户反馈闭环”的任务驱动架构。

**架构：** 采用分阶段迁移，不直接重写全链路。先补统一证据底座和运行时契约，再引入证据规划器并在关系审查器试点接管取图决策，随后让技能包与误报经验进入规划层和执行层，最后补齐用户反馈到误报经验库的正式闭环。

**技术栈：** FastAPI、SQLAlchemy、SQLite、React、TypeScript、Vite、pytest

---

### 任务 1：建立总控迁移契约与特性开关

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/task_planner_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/master_planner_service.py`
- 可能修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime_service.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_orchestrator_flags.py`

**步骤 1：编写失败的测试**

新增测试覆盖：
- 默认仍走现有主流程
- 打开 `AUDIT_ORCHESTRATOR_V2_ENABLED=1` 后，主流程会尝试走新调度分支
- 特性开关关闭时，不会触发新模块导入错误

示例测试骨架：

```python
def test_execute_pipeline_keeps_legacy_path_when_flag_disabled(monkeypatch):
    ...

def test_execute_pipeline_switches_to_v2_path_when_flag_enabled(monkeypatch):
    ...
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_audit_orchestrator_flags.py
```

预期：FAIL，提示缺少 v2 分支控制或行为不符合预期。

**步骤 3：实现最小特性开关**

在 `orchestrator.py` 中增加：
- `AUDIT_ORCHESTRATOR_V2_ENABLED`
- 统一入口 `execute_pipeline(...)` 内对 legacy / v2 的分发

要求：
- legacy 路径保持现状
- v2 路径未完成前可以先做薄包装，不改动业务语义

**步骤 4：运行测试验证通过**

运行：

```bash
./venv/bin/pytest -q tests/test_audit_orchestrator_flags.py
```

预期：PASS

**步骤 5：提交**

```bash
git add tests/test_audit_orchestrator_flags.py services/audit_runtime/orchestrator.py services/task_planner_service.py services/master_planner_service.py
git commit -m "feat: add orchestrator v2 feature flag"
```

---

### 任务 2：实现证据服务层最小版（仅缓存、去重、统一入口）

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/evidence_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/image_pipeline.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_evidence_service.py`

**步骤 1：编写失败的测试**

覆盖：
- 同一页同一证据包重复请求时只渲染一次
- 同一任务批次里重复证据请求会命中缓存
- 支持标准证据包类型：
  - `overview_pack`
  - `paired_overview_pack`
  - `focus_pack`
  - `deep_pack`

示例测试骨架：

```python
def test_evidence_service_reuses_rendered_pack(monkeypatch, tmp_path):
    ...

def test_evidence_service_returns_pack_with_expected_keys(monkeypatch, tmp_path):
    ...
```

**步骤 2：运行测试验证它失败**

运行：

```bash
./venv/bin/pytest -q tests/test_evidence_service.py
```

预期：FAIL，提示缺少 `evidence_service.py` 或缺少统一证据入口。

**步骤 3：实现最小证据服务层**

在 `evidence_service.py` 中实现：
- `EvidenceRequest`
- `EvidencePack`
- `get_evidence_pack(...)`
- 基于 `pdf_page_to_5images(...)` 的缓存与去重

要求：
- 这阶段只接管“怎么取图”和“怎么复用”
- 暂时不接管“取什么图”的决策权
- 不改变现有 relationship / dimension / material 的业务结果

**步骤 4：让三个审查模块改走统一入口**

要求：
- `relationship_discovery.py` 不再直接调用 `pdf_page_to_5images(...)`
- `dimension_audit.py` 的单图语义和图对比都通过证据服务层拿图
- `material_audit.py` 的单页全图也通过证据服务层拿图

**步骤 5：运行测试验证通过**

运行：

```bash
./venv/bin/pytest -q tests/test_evidence_service.py tests/test_relationship_discovery.py tests/test_kimi_service.py
```

预期：PASS

**步骤 6：提交**

```bash
git add services/audit_runtime/evidence_service.py services/audit/image_pipeline.py services/audit/relationship_discovery.py services/audit/dimension_audit.py services/audit/material_audit.py tests/test_evidence_service.py
git commit -m "feat: add shared evidence service foundation"
```

---

### 任务 3：实现证据规划器并定义标准证据请求单

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/evidence_planner.py`
- 可能创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/contracts.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_evidence_planner.py`

**步骤 1：编写失败的测试**

覆盖：
- 关系任务默认先申请 `paired_overview_pack`
- 尺寸任务默认先申请结构化优先；只在需要视觉时申请 `overview_pack` 或 `focus_pack`
- 材料任务默认先申请材料表聚焦证据，不直接申请深度证据包
- 证据规划结果可序列化，便于审图日志和调度追踪

示例测试骨架：

```python
def test_relationship_task_prefers_paired_overview_pack():
    ...

def test_material_task_avoids_deep_pack_by_default():
    ...
```

**步骤 2：运行测试验证它失败**

运行：

```bash
./venv/bin/pytest -q tests/test_evidence_planner.py
```

预期：FAIL，提示缺少证据规划器。

**步骤 3：实现证据规划器**

实现：
- 统一证据包枚举
- 统一证据请求单结构
- 各任务类型的默认策略

要求：
- 证据规划器只输出计划，不直接取图
- 输出应包含：
  - `task_type`
  - `pack_type`
  - `source_sheet_no`
  - `target_sheet_no`
  - `round_index`
  - `reason`

**步骤 4：在总控中接入证据规划**

要求：
- 先只在 v2 分支里使用
- legacy 分支保持不变

**步骤 5：运行测试验证通过**

运行：

```bash
./venv/bin/pytest -q tests/test_evidence_planner.py tests/test_audit_orchestrator_flags.py
```

预期：PASS

**步骤 6：提交**

```bash
git add services/audit_runtime/evidence_planner.py services/audit_runtime/contracts.py services/audit_runtime/orchestrator.py tests/test_evidence_planner.py
git commit -m "feat: add evidence planner contracts"
```

---

### 任务 4：在关系审查器试点收回取图决策权

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 可能修改：`/Users/harry/@dev/ccad/cad-review-backend/services/context_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_relationship_discovery.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_relationship_worker_v2.py`

**步骤 1：编写失败的测试**

覆盖：
- v2 路径下，关系审查器不再按固定 `group_size * 5 图` 盲目组图
- 关系任务先用 `paired_overview_pack`
- 只有在需要时才升级到更重证据包
- 新旧路径在未开启 v2 时结果兼容
- 同一个项目在 legacy 与 v2 路径下，关系类审核结论语义兼容，不出现系统性偏差

**步骤 2：运行测试验证它失败**

运行：

```bash
./venv/bin/pytest -q tests/test_relationship_worker_v2.py tests/test_relationship_discovery.py
```

预期：FAIL

**步骤 3：实现关系审查器 v2**

要求：
- 从“按图分组”转为“按候选关系任务 + 证据计划”
- 关系线索整理器只输出线索，不直接控制发图
- 关系审查器只执行证据规划器下发的取图任务

新增测试建议：

```python
def test_relationship_worker_v2_produces_compatible_findings(monkeypatch, tmp_path):
    ...
```

该测试至少应验证：
- 同一批输入上下文在 legacy / v2 两条路径下，关系问题数量不出现明显漂移
- 关键问题类型与主要图号对保持一致
- 允许证据路径不同，但不允许结果语义失真

**步骤 4：运行测试验证通过**

运行：

```bash
./venv/bin/pytest -q tests/test_relationship_worker_v2.py tests/test_relationship_discovery.py tests/test_plan_audit_tasks_api.py
```

预期：PASS

**步骤 5：提交**

```bash
git add services/audit/relationship_discovery.py services/audit_runtime/orchestrator.py services/context_service.py tests/test_relationship_worker_v2.py tests/test_relationship_discovery.py
git commit -m "feat: migrate relationship worker to evidence planning"
```

---

### 任务 5：将技能包中心升级为规划层与执行层的双入口

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/ai_prompt_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/task_planner_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/evidence_planner.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_skill_pack_runtime_injection.py`

**步骤 1：编写失败的测试**

覆盖：
- 技能包可影响任务优先级
- 技能包可影响证据包选择
- 技能包仍可影响各审查器提示词与判定口径

示例测试骨架：

```python
def test_skill_pack_changes_evidence_strategy(monkeypatch):
    ...

def test_skill_pack_changes_worker_thresholds(monkeypatch):
    ...
```

**步骤 2：运行测试验证它失败**

运行：

```bash
./venv/bin/pytest -q tests/test_skill_pack_runtime_injection.py
```

预期：FAIL

**步骤 3：实现双入口注入**

要求：
- 技能包中心输出结构化配置，不只是 prompt 文本
- 至少支持三类字段：
  - `task_bias`
  - `evidence_bias`
  - `judgement_policy`

**步骤 4：运行测试验证通过**

运行：

```bash
./venv/bin/pytest -q tests/test_skill_pack_runtime_injection.py tests/test_master_planner_service.py
```

预期：PASS

**步骤 5：提交**

```bash
git add services/ai_prompt_service.py services/task_planner_service.py services/audit_runtime/evidence_planner.py services/audit/relationship_discovery.py services/audit/dimension_audit.py services/audit/material_audit.py tests/test_skill_pack_runtime_injection.py
git commit -m "feat: inject skill packs into planning and workers"
```

---

### 任务 6：让误报经验进入运行时规划层与执行层

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/models.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/database.py`
- 可能创建：`/Users/harry/@dev/ccad/cad-review-backend/services/feedback_runtime_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/task_planner_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/evidence_planner.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_feedback_runtime_injection.py`

**步骤 1：编写失败的测试**

覆盖：
- 误报经验会影响任务优先级
- 误报经验会影响证据规划
- 误报经验会直接影响 Worker 阈值与降级策略

**步骤 2：运行测试验证它失败**

运行：

```bash
./venv/bin/pytest -q tests/test_feedback_runtime_injection.py
```

预期：FAIL

**步骤 3：实现运行时经验读取**

要求：
- 不直接复用原始反馈表结构做运行时查询
- 增加一层运行时聚合或映射逻辑
- 输出建议至少包含：
  - `false_positive_rate`
  - `confidence_floor`
  - `needs_secondary_review`
  - `severity_override`

**步骤 4：让三个审查器消费经验**

要求：
- 关系审查器可根据误报经验抬高阈值
- 尺寸审查器可根据误报经验强制补复核
- 材料审查器可根据误报经验降低直接报错概率

**步骤 5：运行测试验证通过**

运行：

```bash
./venv/bin/pytest -q tests/test_feedback_runtime_injection.py tests/test_relationship_discovery.py tests/test_kimi_service.py
```

预期：PASS

**步骤 6：提交**

```bash
git add models.py database.py services/feedback_runtime_service.py services/task_planner_service.py services/audit_runtime/evidence_planner.py services/audit/relationship_discovery.py services/audit/dimension_audit.py services/audit/material_audit.py tests/test_feedback_runtime_injection.py
git commit -m "feat: inject feedback experience into planning and workers"
```

---

### 任务 7：补用户反馈到误报经验库的正式闭环

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/feedback.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/feedback_runtime_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/api/index.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/ProjectStepAudit.tsx`
- 可能修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/types/api.ts`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_feedback_runtime_sync.py`

**步骤 1：编写失败的测试**

覆盖：
- 用户标记误报后，运行时经验层可读取到更新
- 用户确认问题不会被写成误报模式
- 备注信息可作为经验上下文保留

**步骤 2：运行测试验证它失败**

运行：

```bash
./venv/bin/pytest -q tests/test_feedback_runtime_sync.py
```

预期：FAIL

**步骤 3：实现反馈闭环**

要求：
- 审核结果页已有的误报标记能力复用优先
- 后端反馈路由在写入反馈样本后，同步或异步刷新运行时经验索引
- 不允许系统自动把低置信度结果直接当误报经验写入

**步骤 4：运行测试验证通过**

运行：

```bash
./venv/bin/pytest -q tests/test_feedback_runtime_sync.py
```

预期：PASS

**步骤 5：提交**

```bash
git add routers/feedback.py services/feedback_runtime_service.py cad-review-frontend/src/api/index.ts cad-review-frontend/src/pages/ProjectDetail/components/project-detail/ProjectStepAudit.tsx cad-review-frontend/src/types/api.ts tests/test_feedback_runtime_sync.py
git commit -m "feat: connect user feedback to runtime experience store"
```

---

### 任务 8：逐步迁移尺寸审查器与材料审查器到新调度模式

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dimension_worker_v2.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_material_worker_v2.py`

**步骤 1：编写失败的测试**

覆盖：
- 尺寸审查器不再默认先跑完整五图套餐
- 材料审查器不再无上限 `gather`
- 两者都通过证据规划器请求证据包

**步骤 2：运行测试验证它失败**

运行：

```bash
./venv/bin/pytest -q tests/test_dimension_worker_v2.py tests/test_material_worker_v2.py
```

预期：FAIL

**步骤 3：实现尺寸与材料迁移**

要求：
- 尺寸审查器先结构化判断，再按需申请视觉证据
- 材料审查器增加统一并发阀门
- 两者都遵循证据规划器下发的计划

**步骤 4：运行测试验证通过**

运行：

```bash
./venv/bin/pytest -q tests/test_dimension_worker_v2.py tests/test_material_worker_v2.py tests/test_relationship_worker_v2.py
```

预期：PASS

**步骤 5：提交**

```bash
git add services/audit/dimension_audit.py services/audit/material_audit.py services/audit_runtime/orchestrator.py tests/test_dimension_worker_v2.py tests/test_material_worker_v2.py
git commit -m "feat: migrate dimension and material workers to orchestrated evidence flow"
```

---

### 任务 9：运行真实项目回归与切换策略验证

**文件：**
- 使用：`/Users/harry/@dev/ccad/cad-review-backend/utils/manual_check_ai_review_flow.py`
- 可能修改：`/Users/harry/@dev/ccad/cad-review-backend/utils/manual_check_ai_review_flow.py`
- 可能新增：`/Users/harry/@dev/ccad/.artifacts/manual-checks/*`

**步骤 1：补验收脚本参数**

增加：
- 是否启用 v2 总控
- 是否启用证据规划器
- 是否启用反馈经验注入

**步骤 2：跑长项目回归**

至少验证：
- `40+` 张图项目
- 关系审查器试点项目
- 存在误报反馈样本的项目

**步骤 3：比对关键指标**

检查：
- 单次请求图片数是否下降
- 重复渲染是否下降
- 长阶段是否仍有稳定日志
- 最终结果数与误报率是否改善

**步骤 4：提交**

```bash
git add utils/manual_check_ai_review_flow.py .artifacts/manual-checks
git commit -m "test: add orchestrator v2 regression checks"
```

---

### 任务 10：完成前统一验证

**步骤 1：后端验证**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_kimi_service.py tests/test_relationship_discovery.py tests/test_master_planner_service.py tests/test_plan_audit_tasks_api.py tests/test_audit_events_api.py tests/test_audit_runtime_events.py tests/test_audit_orchestrator_flags.py tests/test_evidence_service.py tests/test_evidence_planner.py tests/test_relationship_worker_v2.py tests/test_skill_pack_runtime_injection.py tests/test_feedback_runtime_injection.py tests/test_feedback_runtime_sync.py tests/test_dimension_worker_v2.py tests/test_material_worker_v2.py
./venv/bin/python -m py_compile services/kimi_service.py services/audit_runtime/orchestrator.py services/audit_runtime/evidence_service.py services/audit_runtime/evidence_planner.py services/feedback_runtime_service.py services/audit/relationship_discovery.py services/audit/dimension_audit.py services/audit/material_audit.py routers/feedback.py
```

**步骤 2：前端验证**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm run lint
```

**步骤 3：真实运行验证**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <真实项目ID> --start-audit
```

预期：
- 无语法错误
- 测试通过
- 真实项目可跑
- 日志与结果可追踪

**步骤 4：整理收尾说明**

记录：
- legacy 与 v2 的切换方式
- 哪些模块已迁移
- 哪些模块仍走 legacy

**步骤 5：提交**

```bash
git add .
git commit -m "feat: ship ai audit orchestrator v2 foundation"
```
