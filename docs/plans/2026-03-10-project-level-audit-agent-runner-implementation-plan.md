# 项目级常驻审图 Agent Runner 实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 在现有审图系统中落地一个项目级常驻审图 Agent Runner，把所有 AI 调用统一收口到 Runner / Provider 层，支持项目级会话、子会话池、输出守门、自我修复和统一事件流。

**架构：** 先新增 Runner 抽象和 Provider 抽象，不立即全量替换现有业务 Agent。第一阶段先把公共运行层立起来，再让总控规划Agent和尺寸审查Agent接入同一个 Runner 试点，最后逐步收掉其他业务 Agent 的直接 `call_kimi()` / `call_kimi_stream()` 调用。

**技术栈：** FastAPI、SQLAlchemy、Python asyncio、现有 `kimi_service.py`、现有 `audit_run_events` 事件表、React 前端日志面板、pytest、vitest

---

### 任务 1：定义 Runner / Provider 契约

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_types.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_agent_runner_contracts.py`

**步骤 1：编写失败的测试**

```python
from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.runner_types import RunnerTurnRequest


def test_runner_exposes_project_scope_and_subsessions():
    runner = ProjectAuditAgentRunner(project_id="proj-1", audit_version=3, provider=None)
    request = RunnerTurnRequest(
        agent_key="master_planner_agent",
        turn_kind="planning",
        system_prompt="sys",
        user_prompt="user",
    )
    session = runner.resolve_subsession(request)
    assert session.project_id == "proj-1"
    assert session.agent_key == "master_planner_agent"
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_agent_runner_contracts.py
```

预期：FAIL，提示模块或类型尚不存在。

**步骤 3：提交失败测试**

```bash
git add tests/test_agent_runner_contracts.py
git commit -m "test: add failing tests for audit agent runner contracts"
```

**步骤 4：编写最小实现**

实现最小可用契约，至少包括：

- `RunnerTurnRequest`
- `RunnerTurnResult`
- `RunnerSubsession`
- `ProviderStreamEvent`
- `ProjectAuditAgentRunner`
- `resolve_subsession(...)`

先只做内存级对象，不接数据库。

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/audit_runtime/agent_runner.py services/audit_runtime/runner_types.py tests/test_agent_runner_contracts.py
git commit -m "feat: add audit agent runner contracts"
```

---

### 任务 2：定义 Provider 抽象和 CLI / API 两套 Provider 外壳

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/kimi_service.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/base.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/kimi_api_provider.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/kimi_cli_provider.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_providers.py`

**步骤 1：编写失败的测试**

```python
from services.audit_runtime.providers.kimi_api_provider import KimiApiProvider
from services.audit_runtime.providers.kimi_cli_provider import KimiCliProvider


def test_provider_factory_can_build_api_and_cli():
    assert KimiApiProvider().provider_name == "api"
    assert KimiCliProvider(binary="kimi").provider_name == "cli"
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_providers.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_runner_providers.py
git commit -m "test: add failing tests for runner providers"
```

**步骤 4：编写最小实现**

要求：

- Provider 统一暴露：
  - `run_once(...)`
  - `run_stream(...)`
- `KimiApiProvider` 先包装现有 `call_kimi()` / `call_kimi_stream()`
- `KimiCliProvider` 第一版先只做壳：
  - 能校验 CLI 是否存在
  - 能定义 stdin/stdout 交互接口
  - 先不接真实业务 Agent

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/kimi_service.py services/audit_runtime/providers/base.py services/audit_runtime/providers/kimi_api_provider.py services/audit_runtime/providers/kimi_cli_provider.py tests/test_runner_providers.py
git commit -m "feat: add runner provider abstractions"
```

---

### 任务 3：实现项目级 Runner 会话池和并发模型

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_types.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_agent_runner_sessions.py`

**步骤 1：编写失败的测试**

```python
from services.audit_runtime.agent_runner import ProjectAuditAgentRunner
from services.audit_runtime.runner_types import RunnerTurnRequest


def test_runner_uses_subsessions_per_agent():
    runner = ProjectAuditAgentRunner(project_id="proj-1", audit_version=1, provider=None)
    planning = runner.resolve_subsession(RunnerTurnRequest(agent_key="master_planner_agent", turn_kind="planning", system_prompt="s", user_prompt="u"))
    dimension = runner.resolve_subsession(RunnerTurnRequest(agent_key="dimension_review_agent", turn_kind="dimension", system_prompt="s", user_prompt="u"))
    assert planning.session_key != dimension.session_key
    assert planning.project_id == dimension.project_id == "proj-1"


def test_runner_factory_returns_same_instance_for_same_project():
    r1 = ProjectAuditAgentRunner.get_or_create("proj-1", audit_version=1, provider=None)
    r2 = ProjectAuditAgentRunner.get_or_create("proj-1", audit_version=1, provider=None)
    assert r1 is r2
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_agent_runner_sessions.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_agent_runner_sessions.py
git commit -m "test: add failing tests for runner session pool"
```

**步骤 4：编写最小实现**

要求：

- 不直接在业务代码里裸 `ProjectAuditAgentRunner(...)`
- Runner 必须提供工厂方法或注册表，例如 `get_or_create(...)`
- 同一个项目 + 审核版本只创建一个 Runner 实例
- Runner 内部维护子会话池
- 子会话 key 至少包含：
  - `project_id`
  - `audit_version`
  - `agent_key`
- 子会话共享项目级上下文
- 子会话独立维护：
  - 重试计数
  - 最近一次输出历史
  - 当前 turn 状态

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/audit_runtime/agent_runner.py services/audit_runtime/runner_types.py tests/test_agent_runner_sessions.py
git commit -m "feat: add runner subsession pool"
```

---

### 任务 4：把 Runner 事件模型接入现有事件流

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_event_bridge.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_events_stream_api.py`

**步骤 1：编写失败的测试**

```python
def test_runner_provider_stream_delta_is_written_as_event(db_session):
    ...
    assert event.event_kind == "provider_stream_delta"
    assert event.agent_key == "master_planner_agent"
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_event_bridge.py tests/test_audit_events_stream_api.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_runner_event_bridge.py tests/test_audit_events_stream_api.py
git commit -m "test: add failing tests for runner event bridge"
```

**步骤 4：编写最小实现**

要求：

- `provider_stream_delta` 正式替代 `model_stream_delta`
- `phase_event` 继续保留，不改语义
- 新增 Runner 事件：
  - `runner_session_started`
  - `runner_turn_started`
  - `output_validation_failed`
  - `output_repair_started`
  - `output_repair_succeeded`
- `runner_turn_needs_review`
- `runner_session_failed`
- SSE 和普通事件查询接口都能返回这些事件

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add routers/audit.py services/audit_runtime/state_transitions.py services/audit_runtime/agent_runner.py tests/test_runner_event_bridge.py tests/test_audit_events_stream_api.py
git commit -m "feat: bridge runner events into audit stream"
```

---

### 任务 5：实现 Runner 的输出守门和自我修复

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/output_guard.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_output_guard.py`

**步骤 1：编写失败的测试**

```python
def test_runner_repairs_code_fence_json_before_failing():
    raw = "```json\\n[{\\\"x\\\":1}]\\n```"
    repaired = guard_output(raw)
    assert repaired == [{"x": 1}]

def test_runner_marks_needs_review_after_repair_exhausted():
    ...
    assert result.status == "needs_review"
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_output_guard.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_runner_output_guard.py
git commit -m "test: add failing tests for runner output guard"
```

**步骤 4：编写最小实现**

要求：

- 先做轻修复：
  - 去代码块
  - 去首尾脏字符
  - 复用现有 `_parse_json()` 可复用部分
- 校验失败时触发一次结构补问
- 第二次仍失败时：
  - 不整轮打死
  - 产出 `needs_review`
  - 记录 `output_repair_failed`

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/audit_runtime/agent_runner.py services/audit_runtime/output_guard.py tests/test_runner_output_guard.py
git commit -m "feat: add runner output guard and repair"
```

---

### 任务 6：先让总控规划Agent接入 Runner

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/master_planner_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_master_planner_runner.py`

**步骤 1：编写失败的测试**

```python
def test_master_planner_calls_runner_instead_of_call_kimi(monkeypatch):
    ...
    assert runner_called is True
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_master_planner_runner.py
```

预期：FAIL

**步骤 3：编写最小实现**

要求：

- 总控规划Agent 的 AI 调用改走 Runner
- 业务阶段事件仍由总控规划Agent产出
- 流式 Provider 片段由 Runner 产出
- 出现结构失败时，不直接抛出原始 JSON 解析错误

**步骤 4：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 5：提交**

```bash
git add services/master_planner_service.py services/audit_runtime/orchestrator.py tests/test_master_planner_runner.py
git commit -m "feat: route master planner through audit runner"
```

---

### 任务 7：再让尺寸审查Agent接入 Runner

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dimension_runner.py`

**步骤 1：编写失败的测试**

```python
def test_dimension_agent_uses_runner_and_needs_review_on_bad_json(monkeypatch):
    ...
    assert result.finding.status == "needs_review"
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_dimension_runner.py
```

预期：FAIL

**步骤 3：编写最小实现**

要求：

- 尺寸单图语义分析接入 Runner
- 尺寸图对比接入 Runner
- 遇到 JSON 结构不稳时，优先由 Runner 补救
- 第三次仍要补图或补问时，落到 `needs_review`

**步骤 4：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 5：提交**

```bash
git add services/audit/dimension_audit.py tests/test_dimension_runner.py
git commit -m "feat: route dimension review through audit runner"
```

---

### 任务 8：补 CLI Provider 的最小真实接入能力

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/kimi_cli_provider.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_kimi_cli_provider.py`

**步骤 1：编写失败的测试**

```python
def test_cli_provider_reads_stream_lines_from_process_stdout(monkeypatch):
    ...
    assert chunks == ["你好", "继续输出"]
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_kimi_cli_provider.py
```

预期：FAIL

**步骤 3：编写最小实现**

要求：

- 通过子进程拉起本地 Kimi CLI
- 能持续读取 stdout
- 能把 stdout 转成 `ProviderStreamEvent`
- 支持：
  - 子进程超时
  - 子进程异常退出
  - 手动取消
- 第一版只要求能跑通文本/流式，不要求马上支持全部图片参数

**步骤 4：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 5：提交**

```bash
git add services/audit_runtime/providers/kimi_cli_provider.py tests/test_kimi_cli_provider.py
git commit -m "feat: add minimal kimi cli provider"
```

---

### 任务 9a：迁移关系审查Agent 到 Runner

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_relationship_runner_boundary.py`

**步骤 1：编写失败的测试**

```python
def test_relationship_agent_uses_runner_instead_of_direct_kimi():
    ...
    assert runner_called is True
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_relationship_runner_boundary.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_relationship_runner_boundary.py
git commit -m "test: add failing tests for relationship runner migration"
```

**步骤 4：编写最小实现**

要求：

- 关系审查Agent 的 AI 路径迁到 Runner
- 纯规则路径保持不动
- 改完后单独运行该测试，不和其他 Agent 混改

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/audit/relationship_discovery.py tests/test_relationship_runner_boundary.py
git commit -m "refactor: route relationship review through runner"
```

---

### 任务 9b：迁移索引审查Agent 和材料审查Agent 到 Runner

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_index_material_runner_boundary.py`

**步骤 1：编写失败的测试**

```python
def test_index_and_material_agents_use_runner_instead_of_direct_kimi():
    ...
    assert runner_called_count == 2
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_index_material_runner_boundary.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add tests/test_index_material_runner_boundary.py
git commit -m "test: add failing tests for index and material runner migration"
```

**步骤 4：编写最小实现**

要求：

- 索引 / 材料的 AI 路径迁到 Runner
- 两个 Agent 分两小步改，但放在同一个任务里收尾
- 每改完一个 Agent，就单独跑一次 pytest 确认，不要两个一起改完再一起看
- 保留纯规则路径，不强行全量 AI 化

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS

**步骤 6：提交**

```bash
git add services/audit/index_audit.py services/audit/material_audit.py tests/test_index_material_runner_boundary.py
git commit -m "refactor: route index and material review through runner"
```

---

### 任务 9c：让 Runner 成为 AI 唯一入口的机器可验边界

**文件：**
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_call_boundary.py`

**步骤 1：编写失败的测试**

```python
def test_business_agents_do_not_call_kimi_directly():
    ...
    assert forbidden_calls == []
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_call_boundary.py
rg -n "call_kimi\\(|call_kimi_stream\\(" services/audit
```

预期：FAIL，并能看到业务 Agent 目录仍有直接调用。

**步骤 3：提交失败测试**

```bash
git add tests/test_runner_call_boundary.py
git commit -m "test: add failing boundary test for direct kimi calls"
```

**步骤 4：编写最小实现**

要求：

- `services/audit` 目录下不再出现新的直接调用
- 这一步不再做大改动，只做最后边界清理和入口收口

**步骤 5：运行测试验证它通过**

运行同上命令。  
预期：PASS，`rg` 不再命中业务 Agent 里的直接调用。

**步骤 6：提交**

```bash
git add tests/test_runner_call_boundary.py
git commit -m "refactor: enforce runner as the only ai entrypoint"
```

---

### 任务 10：端到端回归和真实项目验收

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/utils/manual_check_ai_review_flow.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_manual_check_ai_review_flow.py`
- 产物：`/Users/harry/@dev/ccad/.artifacts/manual-checks/*.json`

**步骤 1：编写失败的测试**

```python
def test_manual_check_reports_runner_metrics():
    ...
    assert report["runner"]["provider"] in {"api", "cli"}
    assert "repair_attempts" in report["runner"]
```

**步骤 2：运行测试验证它失败**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_manual_check_ai_review_flow.py
```

预期：FAIL

**步骤 3：编写最小实现**

报告至少新增这些字段：

- `runner.provider`
- `runner.subsessions`
- `runner.repair_attempts`
- `runner.repair_successes`
- `runner.needs_review_count`
- `runner.stream_retry_count`

**步骤 4：运行完整回归**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q \
  tests/test_agent_runner_contracts.py \
  tests/test_runner_providers.py \
  tests/test_agent_runner_sessions.py \
  tests/test_runner_event_bridge.py \
  tests/test_runner_output_guard.py \
  tests/test_master_planner_runner.py \
  tests/test_dimension_runner.py \
  tests/test_kimi_cli_provider.py \
  tests/test_relationship_runner_boundary.py \
  tests/test_index_material_runner_boundary.py \
  tests/test_runner_call_boundary.py \
  tests/test_manual_check_ai_review_flow.py
```

预期：PASS

**步骤 5：运行真实项目验收**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id proj_20260309231506_001af8d5
```

预期：

- 能产出新的 JSON 验收报告
- 不再因为单次 JSON 结构失败直接把整轮打死
- 如果修复失败，更多任务转为 `needs_review`

**步骤 6：提交**

```bash
git add utils/manual_check_ai_review_flow.py tests/test_manual_check_ai_review_flow.py .artifacts/manual-checks
git commit -m "test: add runner end-to-end verification"
```
