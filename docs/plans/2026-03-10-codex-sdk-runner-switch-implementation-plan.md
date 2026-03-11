# Codex SDK 接入现有审图 Runner 并支持前端切换实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 在现有项目级 Runner 架构下新增 Codex SDK 能力，并让前端可以按“本轮审核”切换 Kimi SDK 或 Codex SDK，而不破坏现有审图主链。

**架构：** 保留 Python 后端和现有 Runner，不直接把 Codex SDK 塞进 Python。新增一个本地 Node bridge 去真正接 Codex SDK；Python 侧新增 `CodexSdkProvider` 作为代理壳；前端新增“本轮审核引擎选择”和“默认引擎设置”。

**技术栈：** FastAPI、SQLAlchemy、Python asyncio、Node.js 18+、TypeScript、`@openai/codex-sdk`、React、pytest、vitest

---

### 任务 1：做最小 Codex SDK POC

**文件：**
- 创建：`/Users/harry/@dev/ccad/codex-bridge/package.json`
- 创建：`/Users/harry/@dev/ccad/codex-bridge/src/poc.ts`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_codex_sdk_poc.py`

**步骤 1：编写失败的测试**

```python
def test_codex_sdk_poc_script_exists():
    from pathlib import Path
    assert Path("/Users/harry/@dev/ccad/codex-bridge/src/poc.ts").exists()
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_codex_sdk_poc.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_codex_sdk_poc.py
git commit -m "test: add failing tests for codex sdk poc"
```

**步骤 4：编写最小实现**

要求：

- 初始化 `@openai/codex-sdk`
- 跑一个最小 thread / run
- 能把结果输出到 stdout
- 不先接业务逻辑

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：手工运行 POC**

运行：
```bash
cd /Users/harry/@dev/ccad/codex-bridge
npm install
npx tsx src/poc.ts
```

预期：拿到最小可用输出。

**步骤 7：提交**

```bash
git add /Users/harry/@dev/ccad/codex-bridge/package.json /Users/harry/@dev/ccad/codex-bridge/src/poc.ts tests/test_codex_sdk_poc.py
git commit -m "feat: add codex sdk poc"
```

---

### 任务 2：定义 Node bridge 协议

**文件：**
- 创建：`/Users/harry/@dev/ccad/codex-bridge/src/protocol.ts`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/codex_bridge_types.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_codex_bridge_protocol.py`

**步骤 1：编写失败的测试**

```python
def test_codex_bridge_protocol_supports_start_stream_resume_cancel():
    ...
    assert {"start_turn", "stream_turn", "resume_turn", "cancel_turn"} <= protocol_ops
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_codex_bridge_protocol.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_codex_bridge_protocol.py
git commit -m "test: add failing tests for codex bridge protocol"
```

**步骤 4：编写最小实现**

协议至少定义这些消息：

- `start_turn`
- `stream_turn`
- `resume_turn`
- `cancel_turn`
- `close_thread`

响应至少统一成：

- `provider_stream_delta`
- `phase_event`
- `error`
- `done`

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add codex-bridge/src/protocol.ts cad-review-backend/services/audit_runtime/codex_bridge_types.py tests/test_codex_bridge_protocol.py
git commit -m "feat: define codex bridge protocol"
```

---

### 任务 3：实现 Node bridge 最小服务

**文件：**
- 创建：`/Users/harry/@dev/ccad/codex-bridge/src/server.ts`
- 创建：`/Users/harry/@dev/ccad/codex-bridge/src/session-store.ts`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_codex_bridge_server.py`

**步骤 1：编写失败的测试**

```python
def test_codex_bridge_can_create_and_reuse_thread():
    ...
    assert second["thread_id"] == first["thread_id"]
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_codex_bridge_server.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_codex_bridge_server.py
git commit -m "test: add failing tests for codex bridge server"
```

**步骤 4：编写最小实现**

要求：

- 按子会话 key 保存 thread
- 能创建 thread
- 能复用 thread
- 能流式输出
- 能 cancel 当前 turn

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add codex-bridge/src/server.ts codex-bridge/src/session-store.ts tests/test_codex_bridge_server.py
git commit -m "feat: add codex bridge server"
```

---

### 任务 4：新增 Python 侧 bridge client

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/codex_bridge_client.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_codex_bridge_client.py`

**步骤 1：编写失败的测试**

```python
def test_codex_bridge_client_translates_bridge_events_to_provider_events():
    ...
    assert events[0].event_kind == "provider_stream_delta"
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_codex_bridge_client.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_codex_bridge_client.py
git commit -m "test: add failing tests for codex bridge client"
```

**步骤 4：编写最小实现**

要求：

- Python 能请求 Node bridge
- 能持续读 bridge 流
- 能映射成现有 `ProviderStreamEvent`
- 能发 cancel

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/audit_runtime/codex_bridge_client.py tests/test_codex_bridge_client.py
git commit -m "feat: add codex bridge client"
```

---

### 任务 5：新增 `CodexSdkProvider`

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/codex_sdk_provider.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/base.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_codex_sdk_provider.py`

**步骤 1：编写失败的测试**

```python
def test_codex_sdk_provider_exposes_run_once_and_run_stream():
    ...
    assert provider.provider_name == "codex_sdk"
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_codex_sdk_provider.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_codex_sdk_provider.py
git commit -m "test: add failing tests for codex sdk provider"
```

**步骤 4：编写最小实现**

要求：

- 通过 bridge client 工作
- provider 名固定为 `codex_sdk`
- 支持：
  - `run_once`
  - `run_stream`
  - `cancel`
- 把 thread id 映射回当前 subsession

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/audit_runtime/providers/codex_sdk_provider.py services/audit_runtime/providers/base.py tests/test_codex_sdk_provider.py
git commit -m "feat: add codex sdk provider"
```

---

### 任务 6：扩展 Provider Factory 和本轮审核 provider 选择

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/factory.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/models.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_provider_selection.py`

**步骤 1：编写失败的测试**

```python
def test_audit_run_can_store_requested_runner_provider():
    ...
    assert run.provider_mode == "codex_sdk"
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_provider_selection.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_runner_provider_selection.py
git commit -m "test: add failing tests for runner provider selection"
```

**步骤 4：编写最小实现**

要求：

- `AuditRun` 增加本轮 provider 记录字段
- `start_audit` 支持接收本轮 provider
- factory 能选：
  - `kimi_sdk`
  - `codex_sdk`
  - 保留原有 `api / cli / sdk` 兼容路径

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/audit_runtime/providers/factory.py services/audit_runtime/agent_runner.py routers/audit.py models.py tests/test_runner_provider_selection.py
git commit -m "feat: support per-audit runner provider selection"
```

---

### 任务 7：前端增加默认引擎和本轮审核引擎切换

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/settings/SettingsPrompts.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/api/index.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/types/api.ts`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/AuditProviderSwitch.test.tsx`

**步骤 1：编写失败的测试**

```tsx
it('allows selecting kimi sdk or codex sdk before starting audit', () => {
  ...
  expect(screen.getByLabelText(/Codex SDK/)).toBeInTheDocument()
})
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/pages/ProjectDetail/components/__tests__/AuditProviderSwitch.test.tsx
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add src/pages/ProjectDetail/components/__tests__/AuditProviderSwitch.test.tsx
git commit -m "test: add failing tests for audit provider switch"
```

**步骤 4：编写最小实现**

要求：

- 设置页可选默认引擎
- 启动审核时可覆盖本轮引擎
- 用户界面用大白话显示：
  - `Kimi SDK`
  - `Codex SDK`

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add src/pages/settings/SettingsPrompts.tsx src/pages/ProjectDetail/components/AuditProgressDialog.tsx src/api/index.ts src/types/api.ts src/pages/ProjectDetail/components/__tests__/AuditProviderSwitch.test.tsx
git commit -m "feat: add frontend audit provider switching"
```

---

### 任务 8：让总控规划Agent 和尺寸审查Agent先接 Codex 路线

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/master_planner_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_master_planner_codex_provider.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dimension_codex_provider.py`

**步骤 1：编写失败的测试**

```python
def test_master_planner_uses_codex_provider_when_selected():
    ...
    assert provider_name == "codex_sdk"
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_master_planner_codex_provider.py tests/test_dimension_codex_provider.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_master_planner_codex_provider.py tests/test_dimension_codex_provider.py
git commit -m "test: add failing tests for codex provider routing"
```

**步骤 4：编写最小实现**

要求：

- 本轮 provider 选 `codex_sdk` 时
  - 总控规划Agent 走 Codex
  - 尺寸审查Agent 走 Codex
- 其他 Agent 暂时仍可继续走 Kimi

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/master_planner_service.py services/audit/dimension_audit.py tests/test_master_planner_codex_provider.py tests/test_dimension_codex_provider.py
git commit -m "feat: route planner and dimension agent to codex provider"
```

---

### 任务 9：边界收口

**文件：**
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_codex_runner_boundary.py`

**步骤 1：编写失败的测试**

```python
def test_business_agents_do_not_call_codex_bridge_directly():
    ...
    assert not direct_calls
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_codex_runner_boundary.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_codex_runner_boundary.py
git commit -m "test: add failing tests for codex runner boundary"
```

**步骤 4：编写最小实现**

要求：

- 业务 Agent 不直接调 bridge
- bridge 只允许通过 `CodexSdkProvider`

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add tests/test_codex_runner_boundary.py
git commit -m "test: enforce codex provider boundary"
```

---

### 任务 10：最终回归与真实验收

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/utils/manual_check_ai_review_flow.py`
- 产物：`/Users/harry/@dev/ccad/.artifacts/manual-checks/<project>-codex-switch-check.json`

**步骤 1：补验收指标**

至少输出：

- `provider_mode`
- `provider_names_seen`
- `codex_thread_count`
- `codex_resume_count`
- `codex_cancel_count`
- `codex_stream_event_count`

**步骤 2：跑后端回归**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q \
  tests/test_codex_sdk_poc.py \
  tests/test_codex_bridge_protocol.py \
  tests/test_codex_bridge_server.py \
  tests/test_codex_bridge_client.py \
  tests/test_codex_sdk_provider.py \
  tests/test_runner_provider_selection.py \
  tests/test_master_planner_codex_provider.py \
  tests/test_dimension_codex_provider.py \
  tests/test_codex_runner_boundary.py
```

预期：PASS

**步骤 3：跑前端回归**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm test -- src/pages/ProjectDetail/components/__tests__/AuditProviderSwitch.test.tsx
npm run lint
npm run build
```

预期：PASS

**步骤 4：跑 bridge 手工验收**

运行：
```bash
cd /Users/harry/@dev/ccad/codex-bridge
npm install
npx tsx src/server.ts
```

预期：bridge 能正常启动。

**步骤 5：跑真实项目验收**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/python utils/manual_check_ai_review_flow.py \
  --project-id <真实项目ID> \
  --start-audit \
  --wait-seconds 180 \
  --poll-interval 2 \
  --enable-orchestrator-v2 \
  --enable-evidence-planner \
  --enable-feedback-runtime
```

要求：

- 一次用 `Kimi SDK`
- 一次用 `Codex SDK`
- 报告里能明确看出本轮 provider 和线程/子会话指标

**步骤 6：提交**

```bash
git add utils/manual_check_ai_review_flow.py .artifacts/manual-checks
git commit -m "test: verify codex sdk runner switching"
```
