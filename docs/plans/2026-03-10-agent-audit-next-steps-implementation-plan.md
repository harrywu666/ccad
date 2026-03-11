# AI 审核系统下一阶段演进实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 将现有 Agent 审核系统继续升级为“强结构化结果 + 渐进式证据 + 分层预算 + 放权式经验库 + 共享可疑图优先级”的可控架构。

**架构：** 先把 Finding 结果结构钉死，再让证据规划从“一次性发图”升级成“首轮轻量、低置信度再补图”的渐进式流程。随后在总控层加入分层预算，最后把误报经验库改成提示式接口，并增加一个只共享可疑图优先级的轻量注册表，不做通用消息总线。

**技术栈：** FastAPI、SQLAlchemy、SQLite、React、TypeScript、Vite、pytest

---

### 任务 1：建立统一的 Finding 结构与兼容层

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/models.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/finding_schema.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/contracts.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/types/api.ts`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_finding_schema.py`

**步骤 1：编写失败的测试**

新增测试覆盖：
- `Finding` 支持 `status / source_agent / review_round / triggered_by`
- `Finding` 可以序列化为稳定字典
- 非法字段值会校验失败

示例测试骨架：

```python
def test_finding_schema_serializes_with_review_round():
    finding = Finding(
        sheet_no="A1.01",
        location="立面图-标注A3",
        rule_id="IDX-001",
        finding_type="missing_ref",
        severity="warning",
        status="suspected",
        confidence=0.62,
        source_agent="index_review_agent",
        evidence_pack_id="pack-1",
        review_round=1,
        triggered_by=None,
        description="首轮发现疑似断链",
    )
    assert finding.model_dump()["review_round"] == 1
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_finding_schema.py
```

预期：FAIL，提示缺少 `finding_schema.py` 或字段不完整。

**步骤 3：实现最小结构和兼容转换**

实现：
- `Finding` Pydantic 模型
- 旧结果到新结构的最小兼容转换
- 前端类型增加新字段

要求：
- 第一阶段不删除旧文本描述
- `description` 只做补充字段，不当主判断依据
- 不允许模型自由新增未定义字段

**步骤 4：运行测试验证它通过**

运行：

```bash
./venv/bin/pytest -q tests/test_finding_schema.py
```

预期：PASS

**步骤 5：提交**

```bash
git add \
  /Users/harry/@dev/ccad/cad-review-backend/models.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/finding_schema.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/contracts.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py \
  /Users/harry/@dev/ccad/cad-review-frontend/src/types/api.ts \
  /Users/harry/@dev/ccad/cad-review-backend/tests/test_finding_schema.py
git commit -m "feat: add structured finding schema"
```

---

### 任务 2：让关系审查 Agent 先产出结构化 Finding

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/task_planner_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_relationship_finding_v2.py`

**步骤 1：编写失败的测试**

覆盖：
- 关系审查 `v2` 输出的结果可转换成 `Finding`
- `source_agent=relationship_review_agent`
- 首轮结果默认 `review_round=1`

示例测试骨架：

```python
def test_relationship_worker_v2_returns_structured_findings():
    findings = run_relationship_worker_v2(...)
    assert findings[0].source_agent == "relationship_review_agent"
    assert findings[0].review_round == 1
```

**步骤 2：运行测试验证它失败**

运行：

```bash
./venv/bin/pytest -q tests/test_relationship_finding_v2.py
```

预期：FAIL，提示关系结果仍是旧字典或结构不完整。

**步骤 3：实现最小转换**

要求：
- 仅在 `v2` 路径输出结构化 `Finding`
- legacy 路径保持兼容
- `status` 默认按置信度规则映射为 `suspected / confirmed`

**步骤 4：运行测试验证它通过**

运行：

```bash
./venv/bin/pytest -q tests/test_relationship_finding_v2.py tests/test_relationship_worker_v2.py
```

预期：PASS

**步骤 5：提交**

```bash
git add \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/task_planner_service.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py \
  /Users/harry/@dev/ccad/cad-review-backend/tests/test_relationship_finding_v2.py
git commit -m "feat: return structured findings from relationship agent"
```

---

### 任务 3：让尺寸审查 Agent 和材料审查 Agent 也输出结构化 Finding

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dimension_finding_v2.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_material_finding_v2.py`

**步骤 1：编写失败的测试**

覆盖：
- 尺寸审查 `v2` 输出结构化 `Finding`
- 材料审查 `v2` 输出结构化 `Finding`
- `source_agent` 分别为：
  - `dimension_review_agent`
  - `material_review_agent`
- 首轮结果默认 `review_round=1`

示例测试骨架：

```python
def test_dimension_worker_v2_returns_structured_findings():
    findings = run_dimension_worker_v2(...)
    assert findings[0].source_agent == "dimension_review_agent"
    assert findings[0].review_round == 1


def test_material_worker_v2_returns_structured_findings():
    findings = run_material_worker_v2(...)
    assert findings[0].source_agent == "material_review_agent"
    assert findings[0].review_round == 1
```

**步骤 2：运行测试验证它失败**

运行：

```bash
./venv/bin/pytest -q tests/test_dimension_finding_v2.py tests/test_material_finding_v2.py
```

预期：FAIL，提示尺寸或材料结果仍是旧结构，或缺少 `source_agent / review_round`。

**步骤 3：实现最小转换**

要求：
- 仅在 `v2` 路径输出结构化 `Finding`
- legacy 路径保持兼容
- `status` 默认按置信度规则映射
- 不改变既有规则判定本身，只改变结果承载格式

**步骤 4：运行测试验证它通过**

运行：

```bash
./venv/bin/pytest -q \
  tests/test_dimension_finding_v2.py \
  tests/test_material_finding_v2.py \
  tests/test_dimension_worker_v2.py \
  tests/test_material_worker_v2.py
```

预期：PASS

**步骤 5：提交**

```bash
git add \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py \
  /Users/harry/@dev/ccad/cad-review-backend/tests/test_dimension_finding_v2.py \
  /Users/harry/@dev/ccad/cad-review-backend/tests/test_material_finding_v2.py
git commit -m "feat: return structured findings from dimension and material agents"
```

---

### 任务 4：把证据规划器升级为渐进式首轮轻量计划

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/evidence_planner.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/contracts.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_progressive_evidence_planner.py`

**步骤 1：编写失败的测试**

覆盖：
- `plan_lite(...)` 首轮只给轻量证据包
- 关系任务首轮优先 `paired_overview_pack`
- 不允许首轮直接默认 `deep_pack`

示例测试骨架：

```python
def test_plan_lite_prefers_paired_overview_for_relationship():
    plans = planner.plan_lite(task_type="relationship", ...)
    assert plans[0].pack_type == "paired_overview_pack"
```

**步骤 2：运行测试验证它失败**

运行：

```bash
./venv/bin/pytest -q tests/test_progressive_evidence_planner.py
```

预期：FAIL，提示缺少 `plan_lite` 或仍是一次性计划。

**步骤 3：实现首轮轻量规划**

要求：
- 增加 `plan_lite(...)`
- 输出包含 `round_index=1`
- 首轮只看目录、JSON 摘要和已有候选关系
- 不允许跳过轻量证据直接上最重证据包

**步骤 4：运行测试验证它通过**

运行：

```bash
./venv/bin/pytest -q tests/test_progressive_evidence_planner.py tests/test_evidence_planner.py
```

预期：PASS

**步骤 5：提交**

```bash
git add \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/evidence_planner.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/contracts.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py \
  /Users/harry/@dev/ccad/cad-review-backend/tests/test_progressive_evidence_planner.py
git commit -m "feat: add progressive lite evidence planning"
```

---

### 任务 5：增加按需补图与最多两轮的硬边界

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/evidence_planner.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_progressive_evidence_rounds.py`

**步骤 1：编写失败的测试**

覆盖：
- 当 `confidence < threshold` 时触发第二轮证据
- 第二轮自动升级到更深证据包
- 第三次仍需补图时直接产出 `needs_review`

示例测试骨架：

```python
def test_third_evidence_request_marks_needs_review():
    finding = run_agent_with_three_round_requests(...)
    assert finding.status == "needs_review"
    assert finding.review_round == 3
```

**步骤 2：运行测试验证它失败**

运行：

```bash
./venv/bin/pytest -q tests/test_progressive_evidence_rounds.py
```

预期：FAIL，提示系统仍会继续无限补图，或没有 `needs_review`。

**步骤 3：实现补图决策**

要求：
- 第二轮必须带 `triggered_by`
- 证据包按 `overview -> focus -> deep` 升级
- 第三次仍需补图时停止扩图，直接落 `needs_review`

**步骤 4：运行测试验证它通过**

运行：

```bash
./venv/bin/pytest -q tests/test_progressive_evidence_rounds.py tests/test_relationship_worker_v2.py tests/test_dimension_worker_v2.py tests/test_material_worker_v2.py
```

预期：PASS

**步骤 5：提交**

```bash
git add \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/evidence_planner.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py \
  /Users/harry/@dev/ccad/cad-review-backend/tests/test_progressive_evidence_rounds.py
git commit -m "feat: cap evidence escalation at two rounds"
```

---

### 任务 6：在总控中接入分层视觉预算

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/visual_budget.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/evidence_planner.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_visual_budget.py`

**步骤 1：编写失败的测试**

覆盖：
- 深证据包预算不足时自动降级
- 高优先级任务可动用保底预算
- 预算消耗写入运行日志

示例测试骨架：

```python
def test_visual_budget_downgrades_pack_when_global_budget_low():
    budget = VisualBudget(global_budget=3000, reserve_budget=2000)
    assert budget.request("deep_pack", priority="normal") == "focus_pack"
```

**步骤 2：运行测试验证它失败**

运行：

```bash
./venv/bin/pytest -q tests/test_visual_budget.py
```

预期：FAIL，提示缺少 `VisualBudget` 或没有降级逻辑。

**步骤 3：实现分层预算**

要求：
- 至少包含：
  - `image_budget`
  - `request_budget`
  - `retry_budget`
  - `priority_reserve_budget`
- 预算层只约束证据取用
- 不介入 prompt 构造
- 不直接干预模型调用频率

**步骤 4：运行测试验证它通过**

运行：

```bash
./venv/bin/pytest -q tests/test_visual_budget.py tests/test_audit_runtime_events.py
```

预期：PASS

**步骤 5：提交**

```bash
git add \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/visual_budget.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/evidence_planner.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py \
  /Users/harry/@dev/ccad/cad-review-backend/tests/test_visual_budget.py
git commit -m "feat: add layered visual budget controls"
```

---

### 任务 7：将误报经验库改成放权式 ExperienceHint

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/feedback_runtime_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_experience_hints.py`

**步骤 1：编写失败的测试**

覆盖：
- 经验库输出 `ExperienceHint`
- 支持 `advisory / soft / hard`
- 切换 `intervention_level` 不需要改审查器逻辑

示例测试骨架：

```python
def test_experience_hint_can_downgrade_from_hard_to_advisory_without_worker_changes():
    hint = load_hint(...)
    assert hint.intervention_level in {"hard", "soft", "advisory"}
```

**步骤 2：运行测试验证它失败**

运行：

```bash
./venv/bin/pytest -q tests/test_experience_hints.py
```

预期：FAIL，提示仍是硬注入 profile，而不是 `ExperienceHint`。

**步骤 3：实现放权式接口**

要求：
- 经验库输出结构化 `ExperienceHint`
- 默认优先 `advisory`
- 审查器参考经验，但保留最终判断权
- 未经用户长期确认的样本不提升为 `hard`

**步骤 4：运行测试验证它通过**

运行：

```bash
./venv/bin/pytest -q tests/test_experience_hints.py tests/test_feedback_runtime_injection.py tests/test_feedback_runtime_sync.py
```

预期：PASS

**步骤 5：提交**

```bash
git add \
  /Users/harry/@dev/ccad/cad-review-backend/services/feedback_runtime_service.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py \
  /Users/harry/@dev/ccad/cad-review-backend/tests/test_experience_hints.py
git commit -m "feat: add advisory experience hints"
```

---

### 任务 8：增加共享可疑图注册表，而不是通用消息总线

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/hot_sheet_registry.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_hot_sheet_registry.py`

**步骤 1：编写失败的测试**

覆盖：
- 三个审查 Agent 都可以写入和读取可疑图列表
- 注册表只改变任务优先级
- 不直接改写最终 Finding

示例测试骨架：

```python
def test_hot_sheet_registry_only_changes_priority_not_final_finding():
    registry.publish("A4.03", finding_type="broken_ref", confidence=0.32, source_agent="relationship_review_agent")
    hot = registry.get_hot_sheets()
    assert hot[0].sheet_no == "A4.03"
```

**步骤 2：运行测试验证它失败**

运行：

```bash
./venv/bin/pytest -q tests/test_hot_sheet_registry.py
```

预期：FAIL，提示缺少注册表或当前没有共享优先级能力。

**步骤 3：实现缩小版共享机制**

要求：
- 不做通用消息总线
- 只共享：
  - `sheet_no`
  - `finding_type`
  - `confidence`
  - `source_agent`
- 共享结果只用于优先级调整

**步骤 4：运行测试验证它通过**

运行：

```bash
./venv/bin/pytest -q tests/test_hot_sheet_registry.py tests/test_relationship_worker_v2.py tests/test_dimension_worker_v2.py tests/test_material_worker_v2.py
```

预期：PASS

**步骤 5：提交**

```bash
git add \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/hot_sheet_registry.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py \
  /Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py \
  /Users/harry/@dev/ccad/cad-review-backend/tests/test_hot_sheet_registry.py
git commit -m "feat: add hot sheet registry for agent prioritization"
```

---

### 任务 9：前端渲染结构化 Finding 与状态标签

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/types/api.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/ProjectStepAudit.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/FindingStatusBadge.tsx`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/FindingStatusBadge.test.tsx`

**步骤 1：编写失败的测试**

覆盖：
- 前端能渲染 `confirmed / suspected / needs_review`
- 当 `review_round > 1` 时可显示“已补图复核”
- 旧数据没有这些字段时仍能兼容展示

示例测试骨架：

```tsx
it('renders needs_review badge', () => {
  render(<FindingStatusBadge status="needs_review" reviewRound={3} />);
  expect(screen.getByText('待人工确认')).toBeInTheDocument();
});
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- FindingStatusBadge
```

预期：FAIL，提示缺少组件或标签未实现。

**步骤 3：实现最小渲染**

要求：
- 不靠文本猜状态
- 优先读结构字段
- 旧结果数据缺字段时回退到兼容展示

**步骤 4：运行测试验证它通过**

运行：

```bash
npm test -- FindingStatusBadge
npm run lint
npm run build
```

预期：PASS

**步骤 5：提交**

```bash
git add \
  /Users/harry/@dev/ccad/cad-review-frontend/src/types/api.ts \
  /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/ProjectStepAudit.tsx \
  /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx \
  /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/FindingStatusBadge.tsx \
  /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/FindingStatusBadge.test.tsx
git commit -m "feat: render structured finding statuses in frontend"
```

---

### 任务 10：做整链路回归与量化验收

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/utils/manual_check_ai_review_flow.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_progressive_audit_metrics.py`
- 可能修改：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_plan_audit_tasks_api.py`
- 可能修改：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_runtime_events.py`

**步骤 1：编写失败的测试**

覆盖：
- 同一项目跑 `legacy` 和 `v2`，Finding 字段全部可序列化
- `40` 张图左右的项目里，第二轮补图触发次数 < 总任务数的 `30%`
- 全程预算消耗有日志可追踪

示例测试骨架：

```python
def test_v2_progressive_audit_exposes_budget_and_round_metrics():
    report = run_manual_check(...)
    assert report["round_2_ratio"] < 0.3
    assert "image_budget" in report["budget_usage"]
```

**步骤 2：运行测试验证它失败**

运行：

```bash
./venv/bin/pytest -q tests/test_progressive_audit_metrics.py
```

预期：FAIL，提示回归脚本缺少这些统计。

**步骤 3：实现回归统计与脚本输出**

要求：
- 输出：
  - `round_2_ratio`
  - `needs_review_count`
  - `budget_usage`
  - `structured_finding_coverage`
- 保留 legacy / v2 对照
- `structured_finding_coverage` 定义为：
  - `v2` 路径下，所有 `Finding` 必填字段非空的比例
- 验收门槛：
  - `structured_finding_coverage >= 0.95`

**步骤 4：运行测试验证它通过**

运行：

```bash
./venv/bin/pytest -q tests/test_progressive_audit_metrics.py tests/test_plan_audit_tasks_api.py tests/test_audit_runtime_events.py
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <项目ID> --start-audit
```

预期：PASS，并输出量化指标文件。

**步骤 5：提交**

```bash
git add \
  /Users/harry/@dev/ccad/cad-review-backend/utils/manual_check_ai_review_flow.py \
  /Users/harry/@dev/ccad/cad-review-backend/tests/test_progressive_audit_metrics.py \
  /Users/harry/@dev/ccad/cad-review-backend/tests/test_plan_audit_tasks_api.py \
  /Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_runtime_events.py
git commit -m "test: add progressive audit regression metrics"
```
