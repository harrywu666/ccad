# 误报反馈自循环系统实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 把当前单次“误报备注”流程升级成“反馈会话 + 反馈判定 Agent + 学习门禁 + 结构化记录”的闭环系统，并保持和现有 `audit_results`、`feedback_samples`、`feedback_runtime_service` 兼容衔接。

**架构：** 先补会话层和消息层，让前端从小弹窗升级成会话抽屉；再补反馈判定 Agent 的结构化决策契约；随后引入学习门禁，把 `feedback_samples` 的来源从原始留言切到结构化候选记录；最后再把被接受的经验接到运行时经验聚合层。全程保留旧字段作为兼容视图，不直接推翻现有审图主流程。

**技术栈：** React 19、Vite、TypeScript、FastAPI、SQLAlchemy、pytest、Vitest、现有 `audit.py` / `feedback.py` 路由、现有 `feedback_runtime_service.py`

---

### 任务 1：定义反馈会话数据模型与最小兼容迁移

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/models.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/database.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_feedback_thread_models.py`

**步骤 1：编写失败的测试**

覆盖：
- 可以创建 `FeedbackThread`
- 可以创建 `FeedbackMessage`
- 可以创建 `FeedbackLearningRecord`
- `audit_result_id + open thread` 的约束和基础默认值正确

```python
def test_feedback_thread_defaults(db_session):
    thread = FeedbackThread(project_id="p1", audit_result_id="r1", audit_version=3)
    db_session.add(thread)
    db_session.commit()
    assert thread.status == "open"
    assert thread.learning_decision == "pending"
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_feedback_thread_models.py
```

预期：FAIL，提示模型不存在。

**步骤 3：实现最小模型和数据库初始化补丁**

要求：
- 新增：
  - `FeedbackThread`
  - `FeedbackMessage`
  - `FeedbackLearningRecord`
- 状态字段至少包含设计文档中的第一版枚举
- 保留 `audit_results.feedback_status` / `feedback_note` 作为兼容字段
- `database.py` 补最小建表或迁移逻辑，兼容已有 SQLite 初始化方式

**步骤 4：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 5：提交**

```bash
git add models.py database.py tests/test_feedback_thread_models.py
git commit -m "feat: add feedback thread models"
```

---

### 任务 2：新增反馈会话 API，替代直接写备注的主入口

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/audit.py`
- 可能新增：`/Users/harry/@dev/ccad/cad-review-backend/routers/feedback_threads.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/main.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_feedback_threads_api.py`

**步骤 1：编写失败的测试**

覆盖：
- 可以为某条 `audit_result` 创建反馈线程
- 创建时会写入首条用户消息
- `audit_results.feedback_status` 会同步成“已发起反馈”的兼容状态
- 可以查询线程详情和消息列表

```python
def test_open_feedback_thread_creates_user_message(client, seeded_project):
    resp = client.post(
        f"/api/projects/{seeded_project['project_id']}/audit/results/{seeded_project['result_id']}/feedback-thread",
        json={"message": "这条像是图号别名导致的误报"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["status"] == "open"
    assert payload["messages"][0]["role"] == "user"
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_feedback_threads_api.py
```

预期：FAIL

**步骤 3：实现最小 API**

要求：
- 新增接口：
  - 创建线程
  - 获取线程详情
  - 追加用户消息
  - 获取消息列表
- `audit.py` 原有 `feedback_status=incorrect` 更新逻辑先保留
- 新入口优先走线程，不直接依赖 `feedback_note`

**步骤 4：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 5：提交**

```bash
git add routers/audit.py routers/feedback_threads.py main.py tests/test_feedback_threads_api.py
git commit -m "feat: add feedback thread api"
```

---

### 任务 3：定义反馈判定 Agent 的结构化决策契约与服务层

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/feedback_agent_service.py`
- 可能创建：`/Users/harry/@dev/ccad/cad-review-backend/services/feedback_agent_types.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_feedback_agent_service.py`

**步骤 1：编写失败的测试**

覆盖：
- 服务能基于线程上下文返回 `FeedbackAgentDecision`
- 决策里至少包含：
  - `status`
  - `user_reply`
  - `confidence`
  - `needs_learning_gate`
  - `follow_up_question`
- 当信息不足时，返回 `agent_needs_user_input`

```python
def test_feedback_agent_returns_follow_up_when_context_is_insufficient():
    decision = decide_feedback_thread(
        thread=build_thread(),
        audit_result=build_result(confidence=0.52),
        recent_messages=[{"role": "user", "content": "这是误报"}],
        similar_cases=[],
    )
    assert decision.status == "agent_needs_user_input"
    assert decision.follow_up_question
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_feedback_agent_service.py
```

预期：FAIL

**步骤 3：实现最小服务**

要求：
- 第一版可以先走规则化决策，不强依赖真实模型调用
- 结构化输出严格匹配设计文档
- `user_reply` 和结构化状态拆开
- 保留后续接大模型 Provider 的扩展位
- 第一版相似案例查询只看同一 `rule_id + issue_type`，按 `evidence_score` 降序、时间倒序取最近 `3` 条，不做向量检索
- 写入最小审计记录：至少记录“开始判定”“命中的相似案例”“产出的结构化决策”

**步骤 4：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 5：提交**

```bash
git add services/feedback_agent_service.py services/feedback_agent_types.py tests/test_feedback_agent_service.py
git commit -m "feat: add feedback agent decision service"
```

---

### 任务 4：打通线程消息追加后的 Agent 首轮回复和追问流转

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/feedback_threads.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/feedback_agent_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_feedback_thread_agent_roundtrip.py`

**步骤 1：编写失败的测试**

覆盖：
- 用户发起后，线程里会新增一条 Agent 回复
- 用户追加消息后，线程状态会更新
- 需要追问时，线程状态变成 `agent_needs_user_input`
- Agent 回答后能落到 `resolved_incorrect` 或 `resolved_not_incorrect`

```python
def test_feedback_thread_appends_agent_reply_after_user_message(client, seeded_thread):
    resp = client.post(
        f"/api/projects/{seeded_thread['project_id']}/feedback-threads/{seeded_thread['thread_id']}/messages",
        json={"content": "这张图在项目里一直叫 A06.01a"},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert any(msg["role"] == "agent" for msg in payload["messages"])
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_feedback_thread_agent_roundtrip.py
```

预期：FAIL

**步骤 3：实现最小闭环**

要求：
- 用户消息入库后，立即触发一次决策
- 生成一条 Agent 消息
- 更新线程状态和决策摘要字段
- 第一版同步处理只限任务 3 的规则化决策路径，不接真实模型调用
- 一旦接入真实模型调用，必须改成后台任务 + 前端轮询线程状态，不能继续同步阻塞 API
- 写入最小审计记录：至少记录“用户追加消息”“Agent 回复生成”“线程状态变更”

**步骤 4：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 5：提交**

```bash
git add routers/feedback_threads.py services/feedback_agent_service.py tests/test_feedback_thread_agent_roundtrip.py
git commit -m "feat: add feedback thread agent replies"
```

---

### 任务 5：引入学习门禁，拆开“确认误报”和“是否学习”

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/feedback_learning_gate.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/models.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_feedback_learning_gate.py`

**步骤 1：编写失败的测试**

覆盖：
- 误报成立但缺乏复用性时，返回 `record_only`
- 证据充分且有相似案例时，返回 `accepted_for_learning`
- 信息不足但重要时，返回 `needs_human_review`

```python
def test_learning_gate_marks_project_specific_case_as_record_only():
    decision = evaluate_learning_gate(
        agent_status="resolved_incorrect",
        evidence_score=0.82,
        similar_case_count=0,
        reusability_score=0.2,
    )
    assert decision.learning_decision == "record_only"
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_feedback_learning_gate.py
```

预期：FAIL

**步骤 3：实现最小门禁服务**

要求：
- 独立于 Agent 回复层
- 至少输出：
  - `learning_decision`
  - `reason_code`
  - `reason_text`
  - `evidence_score`
  - `similar_case_count`
  - `reusability_score`
- 创建 `FeedbackLearningRecord`
- 写入最小审计记录：至少记录“门禁输入摘要”“门禁决策结果”“是否进入样本同步”

**步骤 4：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 5：提交**

```bash
git add services/feedback_learning_gate.py models.py tests/test_feedback_learning_gate.py
git commit -m "feat: add feedback learning gate"
```

---

### 任务 6：把 `feedback_samples` 的来源切到结构化学习记录

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/feedback.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/feedback_runtime_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_feedback_sample_sync_v2.py`

**步骤 1：编写失败的测试**

覆盖：
- 只有 `accepted_for_learning` 的线程会生成或刷新 `feedback_samples`
- `record_only` 不进入样本
- `rejected_for_learning` 不进入样本
- `feedback_runtime_service` 仍能读取已采纳经验

```python
def test_feedback_samples_only_sync_from_accepted_learning_records(db_session):
    sync_feedback_sample_from_learning_record(record=accepted_record, db=db_session)
    assert db_session.query(FeedbackSample).count() == 1
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_feedback_sample_sync_v2.py
```

预期：FAIL

**步骤 3：实现最小同步改造**

要求：
- 不打断旧接口兼容性
- 新主路径只从学习记录同步样本
- `feedback_runtime_service` 输入改成更结构化的学习快照
- 旧 `feedback_status=incorrect` 同步样本逻辑逐步降为兼容路径

**步骤 4：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 5：提交**

```bash
git add routers/audit.py routers/feedback.py services/feedback_runtime_service.py tests/test_feedback_sample_sync_v2.py
git commit -m "feat: sync feedback samples from learning records"
```

---

### 任务 7：前端把误报入口从 Popover 升级成反馈会话抽屉

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/ProjectStepAudit.tsx`
- 可能新增：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/FeedbackThreadDrawer.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/api/index.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/types/api.ts`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/FeedbackThreadDrawer.test.tsx`

**步骤 1：编写失败的测试**

覆盖：
- 点击误报旗子后打开抽屉，而不是小弹窗
- 抽屉里显示问题上下文和消息列表
- 用户发送消息后能看到 Agent 回复
- 会显示线程状态和学习状态

```tsx
it('opens feedback drawer and shows agent reply', async () => {
  render(<ProjectStepAudit {...props} />)
  await user.click(screen.getByLabelText(/提交误报反馈/i))
  expect(screen.getByText('反馈会话')).toBeInTheDocument()
})
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- FeedbackThreadDrawer.test.tsx
```

预期：FAIL

**步骤 3：实现最小界面**

要求：
- 入口仍保留旗子按钮
- 右侧抽屉至少展示：
  - 问题描述
  - 规则/来源 Agent/置信度
  - 会话消息
  - 输入框
  - 当前状态
- 第一版先不做复杂动画和流式输出

**步骤 4：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 5：提交**

```bash
git add src/pages/ProjectDetail/components/project-detail/ProjectStepAudit.tsx src/pages/ProjectDetail/components/project-detail/FeedbackThreadDrawer.tsx src/api/index.ts src/types/api.ts src/pages/ProjectDetail/components/__tests__/FeedbackThreadDrawer.test.tsx
git commit -m "feat: replace false positive popover with feedback drawer"
```

---

### 任务 8：在前端展示“确认误报”和“是否学习”的双状态

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/FeedbackThreadDrawer.tsx`
- 可能修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/FindingStatusBadge.tsx`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/FeedbackThreadStatus.test.tsx`

**步骤 1：编写失败的测试**

覆盖：
- `resolved_incorrect + record_only` 会正确显示两层状态
- `resolved_incorrect + accepted_for_learning` 会正确显示两层状态
- `agent_needs_user_input` 会显示“待补充”提示

```tsx
it('renders separate issue resolution and learning decisions', () => {
  render(<FeedbackThreadDrawer thread={threadFixture} />)
  expect(screen.getByText('已判定为误报')).toBeInTheDocument()
  expect(screen.getByText('仅记录，不学习')).toBeInTheDocument()
})
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- FeedbackThreadStatus.test.tsx
```

预期：FAIL

**步骤 3：实现最小状态展示**

要求：
- 问题判定状态和学习状态分开展示
- 文案尽量用大白话，不堆术语
- 保留和现有整体样式一致

**步骤 4：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 5：提交**

```bash
git add src/pages/ProjectDetail/components/project-detail/FeedbackThreadDrawer.tsx src/pages/ProjectDetail/components/FindingStatusBadge.tsx src/pages/ProjectDetail/components/__tests__/FeedbackThreadStatus.test.tsx
git commit -m "feat: show feedback thread decision states"
```

---

### 任务 9：验证日志可回放，保证后面能追查“为什么学了”

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/feedback_threads.py`
- 可能修改：`/Users/harry/@dev/ccad/cad-review-backend/models.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_feedback_thread_audit_log.py`

**步骤 1：编写失败的测试**

覆盖：
- 线程创建会产生日志
- Agent 决策会产生日志
- 学习门禁决策会产生日志
- 可以按线程回放关键事件

```python
def test_feedback_thread_emits_audit_log_for_agent_decision(client, seeded_thread):
    resp = client.post(...)
    assert resp.status_code == 200
    logs = client.get(...).json()
    assert any(item["event_kind"] == "feedback_agent_decision" for item in logs)
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_feedback_thread_audit_log.py
```

预期：FAIL

**步骤 3：补聚合查询和回放接口**

要求：
- 不再把“写日志”留到这个任务才做
- 任务 3、4、5 里发生关键动作时就必须落日志
- 这里主要补：
  - 按线程聚合读取日志
  - 回放关键动作链路
  - 验证日志字段足够解释“为什么判成误报 / 为什么学习或不学习”
- 第一版可以直接复用现有事件表或新增专用表

**步骤 4：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 5：提交**

```bash
git add routers/feedback_threads.py models.py tests/test_feedback_thread_audit_log.py
git commit -m "feat: add feedback thread audit logs"
```

---

### 任务 10：补回归验证，确保旧路径仍可用，新路径能闭环

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_feedback_api.py`
- 可能新增：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_feedback_closed_loop_smoke.py`
- 可能新增：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/ProjectStepAudit.feedback-flow.test.tsx`

**步骤 1：编写失败的测试**

覆盖：
- 旧 `feedback_status=incorrect` 更新路径仍兼容
- 新线程路径能走完整链路：
  - 创建线程
  - Agent 回复
  - 学习门禁落点
  - 样本同步
- 前端不会因为旧数据没有线程而崩溃

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_audit_feedback_api.py tests/test_feedback_closed_loop_smoke.py

cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- ProjectStepAudit.feedback-flow.test.tsx
```

预期：FAIL

**步骤 3：补兼容逻辑和冒烟链路**

要求：
- 旧数据没有线程时，前端仍允许创建新线程
- 新旧路径并存时，不出现重复样本或状态冲突
- 新线程关闭后，`audit_results` 上仍能看到兼容态

**步骤 4：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 5：提交**

```bash
git add cad-review-backend/tests/test_audit_feedback_api.py cad-review-backend/tests/test_feedback_closed_loop_smoke.py cad-review-frontend/src/pages/ProjectDetail/components/__tests__/ProjectStepAudit.feedback-flow.test.tsx
git commit -m "test: add false positive feedback closed loop coverage"
```

---

## 执行顺序建议

推荐按下面顺序推进，别跳步：

1. 先补后端数据模型和线程 API
2. 再补 Agent 决策契约
3. 再补学习门禁
4. 再切 `feedback_samples` 同步来源
5. 最后改前端入口和状态展示

原因：

- 先把事实来源立起来
- 再让界面消费新事实
- 避免先改前端，后端事实模型还没定

---

## 最小可行版本

如果你想先做最小版本，我建议只做到任务 1 到任务 4：

- 有反馈线程
- 有消息
- 有 Agent 首轮回复
- 有状态流转

先不着急做自动学习。

这样就已经能把它从“留言框”升级成“可交互反馈系统”。

---

## 风险提醒

- 风险 1：如果一开始就让线程直接驱动学习，经验库很容易被脏数据污染
- 风险 2：如果前端先改成交互界面，但后端没有结构化状态，最后会退化成假聊天
- 风险 3：如果不保留旧字段兼容，历史数据和已有接口会断

所以第一阶段务必守住两条：

- 先会话化，再学习化
- 先结构化，再智能化
