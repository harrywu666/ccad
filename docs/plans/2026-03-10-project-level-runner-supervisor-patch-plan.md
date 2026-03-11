# 项目级 Runner 在线监督与实时播报补丁实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 把现有项目级 Runner 从“AI 调用中间层”补成“整轮审图在线监督者 + 实时播报者”，重点补上静默卡住检测、明显脏输入拦截、局部重试和用户播报层。

**架构：** 不推翻现有 Runner、Provider、事件表和前端日志面板。在现有项目级 Runner 上新增监督状态、事故处理和播报整理三层能力；业务 Agent 继续通过 Runner 发 AI 请求，但前端默认改看 Runner 整理后的播报，不再直接看原始 provider 碎片。

**技术栈：** FastAPI、SQLAlchemy、Python asyncio、现有 `ProjectAuditAgentRunner`、`kimi_sdk_provider.py`、`audit_run_events`、React/Vitest

---

### 任务 1：补 Runner 监督状态对象

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_types.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_supervisor_state.py`

**步骤 1：编写失败的测试**

```python
def test_runner_subsession_tracks_last_delta_and_current_phase():
    ...
    assert subsession.last_delta_at is None
    assert subsession.current_phase == "idle"
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_supervisor_state.py
```

预期：FAIL，提示字段不存在。

**步骤 3：提交失败测试**

```bash
git add tests/test_runner_supervisor_state.py
git commit -m "test: add failing tests for runner supervisor state"
```

**步骤 4：编写最小实现**

给 `RunnerSubsession` 增加最少这些字段：

- `turn_started_at`
- `last_delta_at`
- `last_progress_at`
- `current_phase`
- `stall_reason`
- `last_broadcast`

并在 `agent_runner.py` 里更新这些状态。

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/audit_runtime/runner_types.py services/audit_runtime/agent_runner.py tests/test_runner_supervisor_state.py
git commit -m "feat: add runner supervisor state tracking"
```

---

### 任务 2：拦截明显脏输入

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_input_guard.py`

**步骤 1：编写失败的测试**

```python
def test_relationship_candidate_self_pair_is_skipped_without_ai_call():
    ...
    assert result == []
    assert fake_provider_calls == 0
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_input_guard.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_runner_input_guard.py
git commit -m "test: add failing tests for runner input guard"
```

**步骤 4：编写最小实现**

至少先拦这几类：

- `source_sheet_no == target_sheet_no`
- source / target 为空
- 明显缺图的关系复核请求

这些脏输入直接跳过，不发给 AI。

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/audit/relationship_discovery.py services/audit/index_audit.py tests/test_runner_input_guard.py
git commit -m "feat: skip invalid runner candidate inputs"
```

---

### 任务 3：给 SDK Provider 加静默卡住检测

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/kimi_sdk_provider.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_kimi_sdk_provider_idle_timeout.py`

**步骤 1：编写失败的测试**

```python
def test_sdk_provider_times_out_when_stream_has_no_new_delta():
    ...
    assert result == "timeout"
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_kimi_sdk_provider_idle_timeout.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_kimi_sdk_provider_idle_timeout.py
git commit -m "test: add failing tests for sdk idle timeout"
```

**步骤 4：编写最小实现**

要求：

- 支持 `AUDIT_SDK_STREAM_IDLE_TIMEOUT_SECONDS`
- 流式开始后，如果超过阈值没有新 delta：
  - 主动 cancel 当前 session turn
  - 抛出可识别的超时异常
- 不等总读超时才发现

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/audit_runtime/providers/kimi_sdk_provider.py tests/test_kimi_sdk_provider_idle_timeout.py
git commit -m "feat: add sdk stream idle timeout"
```

---

### 任务 4：把静默超时接进 Runner 局部重试

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/visual_budget.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_stall_recovery.py`

**步骤 1：编写失败的测试**

```python
def test_runner_retries_stalled_turn_and_marks_needs_review_after_limit():
    ...
    assert result.status == "needs_review"
    assert result.repair_attempts == 0
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_stall_recovery.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_runner_stall_recovery.py
git commit -m "test: add failing tests for runner stall recovery"
```

**步骤 4：编写最小实现**

要求：

- Runner 接住 provider 的静默超时异常
- 先做当前 turn 的局部重试
- 消耗 `retry_budget`
- 超过上限后：
  - 当前 turn 标成 `needs_review`
  - 不直接把整轮审图打死

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/audit_runtime/agent_runner.py services/audit_runtime/visual_budget.py tests/test_runner_stall_recovery.py
git commit -m "feat: add runner stall recovery"
```

---

### 任务 5：新增 Runner 实时播报整理层

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_broadcasts.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_broadcasts.py`

**步骤 1：编写失败的测试**

```python
def test_runner_broadcast_summarizes_provider_state_into_plain_language():
    ...
    assert "正在复核第 15 组候选关系" in message
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_broadcasts.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_runner_broadcasts.py
git commit -m "test: add failing tests for runner broadcasts"
```

**步骤 4：编写最小实现**

至少支持把这些状态整理成大白话播报：

- 正常推进
- 长时间等待
- 输出修复中
- 重试中
- 已转人工确认

播报层输出不要带底层 JSON。

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/audit_runtime/runner_broadcasts.py services/audit_runtime/agent_runner.py tests/test_runner_broadcasts.py
git commit -m "feat: add runner broadcast summaries"
```

---

### 任务 6：把用户播报层写进运行事件

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/audit.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_broadcast_event_bridge.py`

**步骤 1：编写失败的测试**

```python
def test_runner_broadcast_is_written_as_user_facing_event():
    ...
    assert event.event_kind == "runner_broadcast"
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_broadcast_event_bridge.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_runner_broadcast_event_bridge.py
git commit -m "test: add failing tests for runner broadcast events"
```

**步骤 4：编写最小实现**

要求：

- 新增 `runner_broadcast` 事件类型
- 只写整理后的大白话播报
- 原始 provider 流仍保留在调试层，不替代

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/audit_runtime/agent_runner.py routers/audit.py tests/test_runner_broadcast_event_bridge.py
git commit -m "feat: bridge runner broadcasts into audit events"
```

---

### 任务 7：前端默认改看 Runner 播报层

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/auditEventStream.ts`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/AuditEventList.test.tsx`

**步骤 1：编写失败的测试**

```tsx
it('renders runner broadcasts in default stream view', () => {
  ...
  expect(screen.getByText(/正在复核第 15 组候选关系/)).toBeInTheDocument()
})
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/pages/ProjectDetail/components/__tests__/AuditEventList.test.tsx
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add src/pages/ProjectDetail/components/__tests__/AuditEventList.test.tsx
git commit -m "test: add failing tests for runner broadcast stream view"
```

**步骤 4：编写最小实现**

要求：

- 默认 `stream` 视图优先显示 `runner_broadcast`
- 原始 provider 流只放在调试视图
- 普通用户不再直接看到 JSON 碎片

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add src/pages/ProjectDetail/components/AuditEventList.tsx src/pages/ProjectDetail/components/auditEventStream.ts src/pages/ProjectDetail/components/__tests__/AuditEventList.test.tsx
git commit -m "feat: show runner broadcasts in default stream view"
```

---

### 任务 8：最终回归与真实验收

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/utils/manual_check_ai_review_flow.py`
- 产物：`/Users/harry/@dev/ccad/.artifacts/manual-checks/<project>-runner-supervisor-check.json`

**步骤 1：补回归指标**

至少输出：

- `stalled_turn_retries`
- `invalid_input_skipped`
- `runner_broadcast_count`
- `needs_review_count`
- `last_progress_gap_seconds`

**步骤 2：跑后端回归**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q \
  tests/test_runner_supervisor_state.py \
  tests/test_runner_input_guard.py \
  tests/test_kimi_sdk_provider_idle_timeout.py \
  tests/test_runner_stall_recovery.py \
  tests/test_runner_broadcasts.py \
  tests/test_runner_broadcast_event_bridge.py
```

预期：PASS

**步骤 3：跑前端回归**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/pages/ProjectDetail/components/__tests__/AuditEventList.test.tsx
npm run lint
npm run build
```

预期：PASS

**步骤 4：跑真实项目验收**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
AUDIT_RUNNER_PROVIDER=sdk ./venv/bin/python utils/manual_check_ai_review_flow.py \
  --project-id <真实项目ID> \
  --start-audit \
  --wait-seconds 180 \
  --poll-interval 2 \
  --enable-orchestrator-v2 \
  --enable-evidence-planner \
  --enable-feedback-runtime
```

预期：

- 不再出现长时间静默却仍然 `running`
- 自我配对候选被跳过
- 默认前端流看到的是 Runner 播报，而不是原始 JSON

**步骤 5：提交**

```bash
git add utils/manual_check_ai_review_flow.py .artifacts/manual-checks
git commit -m "test: verify runner supervisor and broadcast flow"
```
