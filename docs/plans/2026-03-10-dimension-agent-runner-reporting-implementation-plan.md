# 尺寸审查 Agent 向 Runner 汇报 实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 让尺寸审查 Agent 在运行不稳时先向 Runner 汇报并请求帮助，由 Runner 内部处理后继续推进，避免中途把整轮审核误收成“人工介入”。

**架构：** 保留现有编排器和尺寸审查主逻辑，只在尺寸链路旁边新增一层“员工工作汇报”结构。尺寸 Agent 继续产出问题列表，同时额外产出结构化汇报；Runner 接收这份汇报，转成内部事件和人话播报，再决定是否执行安全动作。

**技术栈：** Python、FastAPI、SQLAlchemy、pytest、现有 audit_runtime Runner 架构

---

### 任务 1：定义尺寸 Agent 的工作汇报结构

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_reports.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_agent_reports.py`

**步骤 1：编写失败的测试**

```python
from services.audit_runtime.agent_reports import DimensionAgentReport


def test_dimension_agent_report_accepts_confirmed_suspected_and_blocking_items():
    report = DimensionAgentReport(
        batch_summary="第 2 批尺寸关系已检查",
        confirmed_findings=[{"sheet_no": "A-101"}],
        suspected_findings=[{"sheet_no": "A-102"}],
        blocking_issues=[{"kind": "unstable_output"}],
        runner_help_request="restart_subsession",
        agent_confidence=0.62,
        next_recommended_action="rerun_current_batch",
    )
    assert report.runner_help_request == "restart_subsession"
```

**步骤 2：运行测试验证它失败**

运行：`./venv/bin/pytest -q tests/test_agent_reports.py`

预期：FAIL，提示 `agent_reports` 或 `DimensionAgentReport` 不存在

**步骤 3：编写最小实现**

实现一个最小 dataclass / pydantic 模型：

```python
@dataclass(slots=True)
class DimensionAgentReport:
    batch_summary: str
    confirmed_findings: list[dict[str, Any]] = field(default_factory=list)
    suspected_findings: list[dict[str, Any]] = field(default_factory=list)
    blocking_issues: list[dict[str, Any]] = field(default_factory=list)
    runner_help_request: str = ""
    agent_confidence: float = 0.0
    next_recommended_action: str = "continue"
```

**步骤 4：运行测试验证它通过**

运行：`./venv/bin/pytest -q tests/test_agent_reports.py`

预期：PASS

**步骤 5：提交**

```bash
git add tests/test_agent_reports.py cad-review-backend/services/audit_runtime/agent_reports.py
git commit -m "feat: add dimension agent report contract"
```

### 任务 2：让尺寸 Agent 产出工作汇报

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dimension_agent_reporting.py`

**步骤 1：编写失败的测试**

```python
def test_dimension_agent_builds_report_when_output_is_unstable(monkeypatch):
    report = _run_dimension_batch_with_unstable_output(...)
    assert report.blocking_issues[0]["kind"] == "unstable_output"
    assert report.runner_help_request == "restart_subsession"
```

**步骤 2：运行测试验证它失败**

运行：`./venv/bin/pytest -q tests/test_dimension_agent_reporting.py`

预期：FAIL，提示没有汇报结构或字段不匹配

**步骤 3：编写最小实现**

在尺寸批处理完成后补一个内部汇报构造函数，例如：

```python
def _build_dimension_agent_report(...):
    return DimensionAgentReport(
        batch_summary=...,
        confirmed_findings=...,
        suspected_findings=...,
        blocking_issues=...,
        runner_help_request=...,
        agent_confidence=...,
        next_recommended_action=...,
    )
```

让尺寸 Agent 在出现以下情况时带上阻塞信息：

- 连续 `output_validation_failed`
- 修复成功后又再次不稳
- 同批次重复重跑

**步骤 4：运行测试验证它通过**

运行：`./venv/bin/pytest -q tests/test_dimension_agent_reporting.py`

预期：PASS

**步骤 5：提交**

```bash
git add tests/test_dimension_agent_reporting.py cad-review-backend/services/audit/dimension_audit.py
git commit -m "feat: add dimension agent status reporting"
```

### 任务 3：把尺寸汇报桥接到 Runner 事件层

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_broadcasts.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dimension_agent_report_bridge.py`

**步骤 1：编写失败的测试**

```python
def test_dimension_agent_report_is_written_as_internal_event():
    append_dimension_agent_report(...)
    assert event.event_kind == "agent_status_reported"
    assert event.agent_key == "dimension_review_agent"


def test_runner_broadcast_hides_internal_report_raw_details():
    message = build_runner_broadcast_from_agent_report(...)
    assert "Runner 正在协助尺寸审查恢复稳定" in message
```

**步骤 2：运行测试验证它失败**

运行：`./venv/bin/pytest -q tests/test_dimension_agent_report_bridge.py`

预期：FAIL

**步骤 3：编写最小实现**

新增一个统一桥接入口，例如：

```python
def append_agent_status_report(...):
    append_run_event(..., event_kind="agent_status_reported", ...)
```

并在播报层把内部汇报翻译成人话。

**步骤 4：运行测试验证它通过**

运行：`./venv/bin/pytest -q tests/test_dimension_agent_report_bridge.py`

预期：PASS

**步骤 5：提交**

```bash
git add tests/test_dimension_agent_report_bridge.py cad-review-backend/services/audit_runtime/state_transitions.py cad-review-backend/services/audit_runtime/runner_broadcasts.py
git commit -m "feat: bridge dimension agent reports into runner events"
```

### 任务 4：让 Runner 根据尺寸汇报决定安全动作

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_observer_feed.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dimension_agent_help_escalation.py`

**步骤 1：编写失败的测试**

```python
def test_runner_prefers_restart_subsession_when_dimension_agent_requests_help():
    decision = dispatch_runner_on_dimension_report(...)
    assert decision.suggested_action == "restart_subsession"


def test_mid_run_dimension_help_request_does_not_end_whole_audit():
    state = handle_dimension_agent_help(...)
    assert state.run_status != "needs_review"
```

**步骤 2：运行测试验证它失败**

运行：`./venv/bin/pytest -q tests/test_dimension_agent_help_escalation.py`

预期：FAIL

**步骤 3：编写最小实现**

实现规则：

- 尺寸 Agent 报 `runner_help_request=restart_subsession` 时
  - Runner 优先尝试 `restart_subsession`
- 如果当前条件不允许重启
  - 降级为 `broadcast_update`
- 不允许中途结束整轮

并把尺寸汇报加入 Observer 快照，让 Observer 知道“员工已经主动求助”。

**步骤 4：运行测试验证它通过**

运行：`./venv/bin/pytest -q tests/test_dimension_agent_help_escalation.py`

预期：PASS

**步骤 5：提交**

```bash
git add tests/test_dimension_agent_help_escalation.py cad-review-backend/services/audit_runtime/agent_runner.py cad-review-backend/services/audit_runtime/runner_observer_feed.py cad-review-backend/services/audit_runtime/state_transitions.py
git commit -m "feat: let runner handle dimension agent help requests"
```

### 任务 5：保证最终只统一向用户收口

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/finding_schema.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_dimension_agent_final_reporting.py`

**步骤 1：编写失败的测试**

```python
def test_dimension_agent_blocking_report_does_not_create_final_issue_by_itself():
    result = run_dimension_blocking_case(...)
    assert result.intermediate_blocking_only is True
    assert result.final_issue_count == 0


def test_final_user_summary_is_emitted_after_phase_completion():
    events = run_dimension_phase(...)
    assert events[-1]["event_kind"] == "phase_completed"
```

**步骤 2：运行测试验证它失败**

运行：`./venv/bin/pytest -q tests/test_dimension_agent_final_reporting.py`

预期：FAIL

**步骤 3：编写最小实现**

保证：

- 内部阻塞汇报不直接写成最终问题
- 最终报告以阶段结束后的整理结果为准
- `Finding.status` 的使用继续只服务内容结果，不再拿来表达中途运行波动

**步骤 4：运行测试验证它通过**

运行：`./venv/bin/pytest -q tests/test_dimension_agent_final_reporting.py`

预期：PASS

**步骤 5：提交**

```bash
git add tests/test_dimension_agent_final_reporting.py cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/services/audit_runtime/finding_schema.py
git commit -m "feat: keep dimension agent blocking reports internal until final summary"
```

### 任务 6：跑相关回归并做真实验收

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/utils/manual_check_ai_review_flow.py`
- 测试：现有测试文件为主

**步骤 1：补充验收统计**

在验收脚本里增加：

- `agent_status_reported_count`
- `runner_help_requested_count`
- `runner_help_resolved_count`

**步骤 2：运行测试**

运行：

```bash
./venv/bin/pytest -q \
  tests/test_agent_reports.py \
  tests/test_dimension_agent_reporting.py \
  tests/test_dimension_agent_report_bridge.py \
  tests/test_dimension_agent_help_escalation.py \
  tests/test_dimension_agent_final_reporting.py \
  tests/test_runner_observer_feed.py \
  tests/test_runner_observer_llm_loop.py \
  tests/test_runner_action_gate.py
```

预期：PASS

**步骤 3：真实项目验收**

运行：

```bash
./venv/bin/python utils/manual_check_ai_review_flow.py \
  --project-id proj_20260309231506_001af8d5 \
  --start-audit \
  --provider-mode kimi_sdk \
  --wait-seconds 180 \
  --poll-interval 2
```

重点看：

- 尺寸 Agent 是否会先发 `agent_status_reported`
- Runner 是否出现 `runner_help_requested` / `runner_help_resolved`
- 中途是否还会把整轮误收成“人工介入”
- 最终报告是否只在整轮完成后统一出现

**步骤 4：提交**

```bash
git add cad-review-backend/utils/manual_check_ai_review_flow.py
git commit -m "test: add acceptance checks for dimension agent reporting"
```

---

计划已完成并保存到 `docs/plans/2026-03-10-dimension-agent-runner-reporting-implementation-plan.md`。两种执行选项：

**1. 子代理驱动（本会话）** - 我为每个任务分派新的子代理，在任务之间进行审查，快速迭代

**2. 并行会话（单独会话）** - 打开新会话并使用 executing-plans，批量执行并设置检查点

选择哪种方式？
