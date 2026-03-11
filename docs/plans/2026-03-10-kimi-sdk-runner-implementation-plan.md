# 基于 kimi-agent-sdk 的审图 Runner 接入实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 让现有项目级审图 Runner 正式接入 `kimi-agent-sdk`，本地优先复用 Kimi Code 登录态，线上继续保留 API 兜底。

**架构：** 在不推翻现有 Runner 架构的前提下，新增 `KimiSdkProvider`。业务 Agent 继续只和项目级 Runner 打交道，Runner 下面通过子会话池管理多个 SDK Session。先做本机 POC，确认能吃到 Kimi Code 运行时，再逐步替换现有 API/CLI provider 入口。

**技术栈：** Python、pytest、`kimi-agent-sdk`、现有 `ProjectAuditAgentRunner`、现有运行事件流、SQLite。

---

### 任务 1：先验证 SDK 能否复用本机 Kimi Code 登录态

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_kimi_sdk_poc.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/scripts/kimi_sdk_poc.py`
- 参考：`/tmp/kimi-agent-sdk/python/README.md`
- 参考：`/tmp/kimi-agent-sdk/guides/python/session.md`

**步骤 1：编写失败的测试**

```python
def test_kimi_sdk_poc_script_exists():
    from pathlib import Path

    script = Path("/Users/harry/@dev/ccad/cad-review-backend/scripts/kimi_sdk_poc.py")
    assert script.exists()
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_kimi_sdk_poc.py
```

预期：FAIL，提示 `kimi_sdk_poc.py` 不存在。

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_kimi_sdk_poc.py
git commit -m "test: add failing kimi sdk poc test"
```

**步骤 4：编写最小 POC 脚本**

要求：

- 脚本尝试 `Session.create(...)`
- 在当前工作目录发一个最小 prompt
- 打印：
  - `session_created`
  - `received_text`
  - `received_think`
  - `approval_requested`
  - `failed_reason`
- 不把它接进业务链，只作为一次性验证工具

建议结构：

```python
async def main():
    async with await Session.create(work_dir=KaosPath.cwd()) as session:
        async for msg in session.prompt("请只回复：ok"):
            ...
```

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_kimi_sdk_poc.py
```

预期：PASS

**步骤 6：运行本机 POC**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/python scripts/kimi_sdk_poc.py
```

预期：

- 如果本机登录态可用，输出 `session_created` 并收到文本流
- 如果不可用，明确打印鉴权失败原因

**步骤 7：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_kimi_sdk_poc.py scripts/kimi_sdk_poc.py
git commit -m "feat: add kimi sdk runtime poc"
```

---

### 任务 2：把 SDK Provider 契约先立起来

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_kimi_sdk_provider.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/kimi_sdk_provider.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/base.py`

**步骤 1：编写失败的测试**

```python
async def test_kimi_sdk_provider_exposes_run_once_and_run_stream():
    from services.audit_runtime.providers.kimi_sdk_provider import KimiSdkProvider

    provider = KimiSdkProvider()
    assert hasattr(provider, "run_once")
    assert hasattr(provider, "run_stream")
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_kimi_sdk_provider.py
```

预期：FAIL，提示模块或类不存在。

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_kimi_sdk_provider.py
git commit -m "test: add failing kimi sdk provider tests"
```

**步骤 4：编写最小实现**

要求：

- `KimiSdkProvider` 先实现：
  - `run_once(...)`
  - `run_stream(...)`
- 先不接真实 SDK 逻辑，只保证接口形状和返回类型对齐现有 provider 契约
- 输出事件统一使用：
  - `provider_stream_delta`
  - `phase_event`

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_kimi_sdk_provider.py
```

预期：PASS

**步骤 6：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_kimi_sdk_provider.py services/audit_runtime/providers/kimi_sdk_provider.py services/audit_runtime/providers/base.py
git commit -m "feat: add kimi sdk provider skeleton"
```

---

### 任务 3：给 Runner 加 SDK Session 工厂和项目级单例对接

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_kimi_sdk_session_pool.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_types.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/kimi_sdk_provider.py`

**步骤 1：编写失败的测试**

```python
def test_runner_factory_returns_same_instance_for_same_project():
    from services.audit_runtime.agent_runner import ProjectAuditAgentRunner

    r1 = ProjectAuditAgentRunner.get_or_create("proj-1", audit_version=1, provider=None)
    r2 = ProjectAuditAgentRunner.get_or_create("proj-1", audit_version=1, provider=None)
    assert r1 is r2


def test_kimi_sdk_provider_uses_independent_subsessions_per_agent():
    ...
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_kimi_sdk_session_pool.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_kimi_sdk_session_pool.py
git commit -m "test: add failing kimi sdk session pool tests"
```

**步骤 4：实现最小会话池**

要求：

- `ProjectAuditAgentRunner` 继续保持项目级单例
- `KimiSdkProvider` 内部维护子会话池
- 子会话按 `agent_key` 隔离
- 同一个 `agent_key` 下尽量复用已有 session
- 不允许把所有业务 Agent 都塞进同一个 SDK Session

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_kimi_sdk_session_pool.py tests/test_agent_runner_sessions.py
```

预期：PASS

**步骤 6：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_kimi_sdk_session_pool.py services/audit_runtime/agent_runner.py services/audit_runtime/runner_types.py services/audit_runtime/providers/kimi_sdk_provider.py
git commit -m "feat: add kimi sdk subsession pool"
```

---

### 任务 4：把 SDK 流式事件桥接到现有运行事件流

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_kimi_sdk_event_bridge.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/kimi_sdk_provider.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py`

**步骤 1：编写失败的测试**

```python
async def test_kimi_sdk_provider_emits_provider_stream_delta_and_phase_event():
    ...
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_kimi_sdk_event_bridge.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_kimi_sdk_event_bridge.py
git commit -m "test: add failing kimi sdk event bridge tests"
```

**步骤 4：实现事件映射**

要求：

- SDK 的 `TextPart` -> `provider_stream_delta`
- SDK 的 `ThinkPart` -> `phase_event`
- SDK 的 `StatusUpdate` -> 可读进度事件
- SDK 的 `ApprovalRequest` -> `phase_event`，并带明确原因
- 保留原始 meta，方便后台排查

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_kimi_sdk_event_bridge.py tests/test_runner_event_bridge.py
```

预期：PASS

**步骤 6：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_kimi_sdk_event_bridge.py services/audit_runtime/providers/kimi_sdk_provider.py services/audit_runtime/agent_runner.py
git commit -m "feat: bridge kimi sdk stream events"
```

---

### 任务 5：先把总控规划 Agent 切到 SDK Provider

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_master_planner_sdk_provider.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/master_planner_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/factory.py`

**步骤 1：编写失败的测试**

```python
async def test_master_planner_can_use_kimi_sdk_provider():
    ...
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_master_planner_sdk_provider.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_master_planner_sdk_provider.py
git commit -m "test: add failing master planner sdk provider tests"
```

**步骤 4：实现接入**

要求：

- `factory.py` 支持 `sdk|api|cli|auto`
- 本地优先策略先定成：
  - `sdk`
  - `cli`
  - `api`
- `master_planner_service.py` 不再关心底层实现，只通过 factory 拿 provider

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_master_planner_sdk_provider.py tests/test_master_planner_runner.py tests/test_master_planner_stream.py
```

预期：PASS

**步骤 6：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_master_planner_sdk_provider.py services/master_planner_service.py services/audit_runtime/providers/factory.py
git commit -m "feat: route master planner through kimi sdk provider"
```

---

### 任务 6：把尺寸审查 Agent 切到 SDK Provider

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dimension_sdk_provider.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`

**步骤 1：编写失败的测试**

```python
async def test_dimension_agent_can_use_kimi_sdk_provider():
    ...
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_dimension_sdk_provider.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_dimension_sdk_provider.py
git commit -m "test: add failing dimension sdk provider tests"
```

**步骤 4：实现接入**

要求：

- 尺寸单图分析和图对比都走 Runner + SDK Provider
- 继续保留已有：
  - Finding 结构
  - 渐进式证据
  - 预算
  - 取消

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_dimension_sdk_provider.py tests/test_dimension_worker_v2.py tests/test_dimension_runner.py
```

预期：PASS

**步骤 6：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_dimension_sdk_provider.py services/audit/dimension_audit.py
git commit -m "feat: route dimension agent through kimi sdk provider"
```

---

### 任务 7：把关系 / 索引 / 材料分批迁到 SDK Provider

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_relationship_sdk_provider.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_index_material_sdk_provider.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`

**步骤 1：编写失败的测试**

```python
async def test_relationship_agent_can_use_kimi_sdk_provider():
    ...


async def test_index_and_material_agents_can_use_kimi_sdk_provider():
    ...
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_relationship_sdk_provider.py tests/test_index_material_sdk_provider.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_relationship_sdk_provider.py tests/test_index_material_sdk_provider.py
git commit -m "test: add failing sdk provider tests for remaining agents"
```

**步骤 4：先迁关系**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_relationship_sdk_provider.py tests/test_relationship_worker_v2.py
```

预期：PASS

**步骤 5：提交关系迁移**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_relationship_sdk_provider.py services/audit/relationship_discovery.py
git commit -m "feat: route relationship agent through kimi sdk provider"
```

**步骤 6：再迁索引和材料**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_index_material_sdk_provider.py tests/test_index_worker_ai_review.py tests/test_material_worker_v2.py
```

预期：PASS

**步骤 7：提交索引和材料迁移**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_index_material_sdk_provider.py services/audit/index_audit.py services/audit/material_audit.py
git commit -m "feat: route index and material agents through kimi sdk provider"
```

---

### 任务 8：把输出守门和自动修复接到 SDK 路径

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_kimi_sdk_output_guard.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/output_guard.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/kimi_sdk_provider.py`

**步骤 1：编写失败的测试**

```python
def test_kimi_sdk_invalid_json_is_repaired_or_marked_needs_review():
    ...
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_kimi_sdk_output_guard.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_kimi_sdk_output_guard.py
git commit -m "test: add failing sdk output guard tests"
```

**步骤 4：实现**

要求：

- SDK 输出进 Runner 后，仍然先过统一 output guard
- 半截 JSON、代码块包裹 JSON、字段缺失，都先尝试整理
- 整理失败才转 `needs_review`

**步骤 5：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_kimi_sdk_output_guard.py tests/test_runner_output_guard.py
```

预期：PASS

**步骤 6：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_kimi_sdk_output_guard.py services/audit_runtime/output_guard.py services/audit_runtime/agent_runner.py services/audit_runtime/providers/kimi_sdk_provider.py
git commit -m "feat: add output guard for kimi sdk provider"
```

---

### 任务 9：收掉业务 Agent 直连底层 AI 的旧入口

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_sdk_runner_boundary.py`
- 参考检查：`/Users/harry/@dev/ccad/cad-review-backend/services`

**步骤 1：编写边界测试**

```python
def test_business_agents_do_not_call_raw_kimi_functions():
    ...
```

**步骤 2：运行静态检查**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
rg -n "call_kimi\\(|call_kimi_stream\\(" services/audit services/master_planner_service.py
```

预期：

- 业务 Agent 目录下不再出现直接调用
- 只允许在 provider 实现层出现

**步骤 3：运行测试验证边界**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_sdk_runner_boundary.py
```

预期：PASS

**步骤 4：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add tests/test_sdk_runner_boundary.py
git commit -m "test: enforce sdk runner boundary"
```

---

### 任务 10：做一轮本地真实验收并输出报告

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/utils/manual_check_ai_review_flow.py`
- 产物目录：`/Users/harry/@dev/ccad/.artifacts/manual-checks/`

**步骤 1：补充验收输出字段**

要求新增：

- `provider_mode`
- `sdk_session_reuse_count`
- `sdk_repair_attempts`
- `sdk_repair_successes`
- `sdk_needs_review_count`
- `sdk_stream_event_count`

**步骤 2：跑针对性测试**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q \
  tests/test_kimi_sdk_poc.py \
  tests/test_kimi_sdk_provider.py \
  tests/test_kimi_sdk_session_pool.py \
  tests/test_kimi_sdk_event_bridge.py \
  tests/test_master_planner_sdk_provider.py \
  tests/test_dimension_sdk_provider.py \
  tests/test_relationship_sdk_provider.py \
  tests/test_index_material_sdk_provider.py \
  tests/test_kimi_sdk_output_guard.py \
  tests/test_sdk_runner_boundary.py
```

预期：PASS

**步骤 3：跑真实项目验收**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
AUDIT_RUNNER_PROVIDER=sdk \
./venv/bin/python utils/manual_check_ai_review_flow.py \
  --project-id proj_20260309231506_001af8d5 \
  --start-audit \
  --wait-seconds 180 \
  --poll-interval 2 \
  --enable-orchestrator-v2 \
  --enable-evidence-planner \
  --enable-feedback-runtime
```

预期：

- 本地机器如果登录态可用，Runner 能直接走 SDK
- 生成新的人工验收 JSON 报告

**步骤 4：补一条大回归**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q \
  tests/test_master_planner_service.py \
  tests/test_master_planner_stream.py \
  tests/test_plan_audit_tasks_api.py \
  tests/test_relationship_worker_v2.py \
  tests/test_dimension_worker_v2.py \
  tests/test_index_worker_ai_review.py \
  tests/test_material_worker_v2.py \
  tests/test_agent_runner_sessions.py \
  tests/test_runner_event_bridge.py \
  tests/test_runner_output_guard.py
```

预期：PASS

**步骤 5：提交**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
git add utils/manual_check_ai_review_flow.py .artifacts/manual-checks
git commit -m "feat: validate kimi sdk runner on local runtime"
```

---

## 最终验收标准

完成后必须同时满足：

1. 本机已登录 Kimi Code 时，SDK 路径能跑通至少一次真实 Runner 调用。
2. 业务 Agent 不再直接出现 `call_kimi()` / `call_kimi_stream()`。
3. 项目级 Runner 仍然是单例，但不同业务 Agent 用独立子会话。
4. `provider_stream_delta`、`phase_event`、取消、修复事件都能正常写入运行事件流。
5. JSON 坏掉时，Runner 先补救，不再直接把整轮审图打死。
6. 人工验收报告能明确看出这轮到底走的是 `sdk`、`cli` 还是 `api`。

