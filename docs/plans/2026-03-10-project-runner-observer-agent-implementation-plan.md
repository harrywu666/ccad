# 项目级 Runner Observer Agent 实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 在现有审图主流程不推翻的前提下，落地“每个项目一条持续长会话”的 Runner Observer Agent，让它全程接入大模型观察现场、持续产出判断、并通过安全闸门执行有限动作。

**架构：** 保留现有编排器、业务审查模块、事件流和结果表。新增项目级观察会话、观察面板整理层、结构化决策层、动作闸门层，以及 Runner 专用人格提示资产；先做“全程观察 + 结构化建议 + 低风险自动动作”，再做更强的自动接管。

**技术栈：** FastAPI、SQLAlchemy、Python asyncio、现有 `ProjectAuditAgentRunner` / Provider 层、现有 `audit_run_events` 事件流、pytest、现有 `ai_prompt_service.py`

---

### 任务 1：定义 Observer 决策契约和记忆对象

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_observer_types.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_observer_types.py`

**Step 1: Write the failing test**

```python
from services.audit_runtime.runner_observer_types import (
    RunnerObserverDecision,
    RunnerObserverMemory,
)


def test_runner_observer_decision_exposes_action_and_reason():
    decision = RunnerObserverDecision(
        summary="当前像是假活",
        risk_level="high",
        suggested_action="restart_subsession",
        reason="最近 180 秒没有新正文输出，但步骤仍显示 running",
        should_intervene=True,
        confidence=0.91,
    )
    assert decision.suggested_action == "restart_subsession"
    assert decision.should_intervene is True


def test_runner_observer_memory_tracks_current_summary_and_interventions():
    memory = RunnerObserverMemory(project_id="proj-1", audit_version=3)
    assert memory.project_summary == ""
    assert memory.intervention_history == []
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_observer_types.py
```

Expected: FAIL，提示模块或类型不存在。

**Step 3: Commit the failing test**

```bash
git add tests/test_runner_observer_types.py
git commit -m "test: add failing tests for runner observer types"
```

**Step 4: Write the minimal implementation**

在 `runner_observer_types.py` 中定义最小契约，至少包括：

- `RunnerObserverDecision`
  - `summary`
  - `risk_level`
  - `suggested_action`
  - `reason`
  - `should_intervene`
  - `confidence`
  - `user_facing_broadcast`
- `RunnerObserverFeedSnapshot`
- `RunnerObserverMemory`
  - `project_summary`
  - `current_focus`
  - `recent_events`
  - `intervention_history`

**Step 5: Run test to verify it passes**

运行同上命令。  
Expected: PASS

**Step 6: Commit**

```bash
git add services/audit_runtime/runner_observer_types.py tests/test_runner_observer_types.py
git commit -m "feat: add runner observer types"
```

---

### 任务 2：新增 Runner Observer 的 Agent.md / soul.md 提示资产和拼装器

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/prompts/runner_observer/Agent.md`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/prompts/runner_observer/soul.md`
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_observer_prompt.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_observer_prompt.py`

**Step 1: Write the failing test**

```python
from services.audit_runtime.runner_observer_prompt import build_runner_observer_system_prompt


def test_runner_observer_prompt_includes_agent_and_soul_sections():
    prompt = build_runner_observer_system_prompt()
    assert "项目级 Runner Observer Agent" in prompt
    assert "你是整轮审图的 AI 值班长" in prompt
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_observer_prompt.py
```

Expected: FAIL

**Step 3: Commit the failing test**

```bash
git add tests/test_runner_observer_prompt.py
git commit -m "test: add failing tests for runner observer prompt"
```

**Step 4: Write the minimal implementation**

要求：

- 把设计稿中的 `Agent.md` 草案写入 `prompts/runner_observer/Agent.md`
- 把设计稿中的 `soul.md` 草案写入 `prompts/runner_observer/soul.md`
- `runner_observer_prompt.py` 提供：
  - `load_runner_observer_agent_prompt()`
  - `load_runner_observer_soul_prompt()`
  - `build_runner_observer_system_prompt()`
- 第一版直接从 markdown 读取并拼接，不先接数据库覆盖

**Step 5: Run test to verify it passes**

运行同上命令。  
Expected: PASS

**Step 6: Commit**

```bash
git add prompts/runner_observer/Agent.md prompts/runner_observer/soul.md services/audit_runtime/runner_observer_prompt.py tests/test_runner_observer_prompt.py
git commit -m "feat: add runner observer prompt assets"
```

---

### 任务 3：实现“项目观察面板”整理层

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_observer_feed.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_observer_feed.py`

**Step 1: Write the failing test**

```python
from services.audit_runtime.runner_observer_feed import build_observer_snapshot


def test_observer_snapshot_summarizes_project_state_and_recent_events():
    snapshot = build_observer_snapshot(
        project_id="proj-1",
        audit_version=2,
        runtime_status={"status": "running", "current_step": "尺寸复核"},
        recent_events=[
            {"event_kind": "runner_broadcast", "message": "尺寸审查Agent 正在比对主尺寸链"},
            {"event_kind": "runner_turn_retrying", "message": "Runner 正在重试"},
        ],
    )
    assert snapshot.current_step == "尺寸复核"
    assert snapshot.recent_events[0]["event_kind"] == "runner_broadcast"
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_observer_feed.py
```

Expected: FAIL

**Step 3: Commit the failing test**

```bash
git add tests/test_runner_observer_feed.py
git commit -m "test: add failing tests for runner observer feed"
```

**Step 4: Write the minimal implementation**

要求：

- `build_observer_snapshot(...)` 至少能整理：
  - `project_id`
  - `audit_version`
  - `runtime_status`
  - `current_step`
  - `recent_events`
  - `current_risk_signals`
  - `available_actions`
- 先只用现有运行状态和事件列表组装，不先接数据库查询封装层
- 动作清单第一版固定返回白名单：
  - `observe_only`
  - `broadcast_update`
  - `cancel_turn`
  - `restart_subsession`
  - `rerun_current_step`
  - `mark_needs_review`

**Step 5: Run test to verify it passes**

运行同上命令。  
Expected: PASS

**Step 6: Commit**

```bash
git add services/audit_runtime/runner_observer_feed.py tests/test_runner_observer_feed.py
git commit -m "feat: add runner observer feed builder"
```

---

### 任务 4：实现项目级 Runner Observer 长会话和观察循环

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_observer_session.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/base.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_observer_session.py`

**Step 1: Write the failing test**

```python
from services.audit_runtime.runner_observer_session import ProjectRunnerObserverSession
from services.audit_runtime.runner_observer_types import RunnerObserverDecision


class FakeObserverProvider:
    provider_name = "sdk"

    async def observe_once(self, snapshot, memory):  # noqa: ANN001
        return RunnerObserverDecision(
            summary="当前流程正常推进",
            risk_level="low",
            suggested_action="observe_only",
            reason="最近一直有新输出",
            should_intervene=False,
            confidence=0.88,
            user_facing_broadcast="Runner 正在继续观察当前流程",
        )


async def test_observer_session_reuses_same_instance_per_project():
    s1 = ProjectRunnerObserverSession.get_or_create("proj-1", audit_version=1, provider=FakeObserverProvider())
    s2 = ProjectRunnerObserverSession.get_or_create("proj-1", audit_version=1, provider=FakeObserverProvider())
    assert s1 is s2
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_observer_session.py
```

Expected: FAIL

**Step 3: Commit the failing test**

```bash
git add tests/test_runner_observer_session.py
git commit -m "test: add failing tests for runner observer session"
```

**Step 4: Write the minimal implementation**

要求：

- 在 `providers/base.py` 增加 Observer 能力接口：
  - `observe_once(snapshot, memory)`
- `ProjectRunnerObserverSession` 提供：
  - `get_or_create(project_id, audit_version, provider)`
  - `observe(snapshot)`
  - 项目级注册表
  - 内存级 `RunnerObserverMemory`
- 第一版先不做后台常驻协程，只做“关键事件触发一次观察判断”

**Step 5: Run test to verify it passes**

运行同上命令。  
Expected: PASS

**Step 6: Commit**

```bash
git add services/audit_runtime/providers/base.py services/audit_runtime/runner_observer_session.py tests/test_runner_observer_session.py
git commit -m "feat: add runner observer session"
```

---

### 任务 5：实现 Action Gate，把观察判断变成安全动作

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_action_gate.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_action_gate.py`

**Step 1: Write the failing test**

```python
from services.audit_runtime.runner_action_gate import RunnerActionGate


def test_action_gate_allows_restart_subsession_but_rejects_unknown_action():
    gate = RunnerActionGate(project_root="/tmp/project")
    allowed = gate.check_allowed("restart_subsession")
    rejected = gate.check_allowed("delete_workspace")
    assert allowed.allowed is True
    assert rejected.allowed is False
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_action_gate.py
```

Expected: FAIL

**Step 3: Commit the failing test**

```bash
git add tests/test_runner_action_gate.py
git commit -m "test: add failing tests for runner action gate"
```

**Step 4: Write the minimal implementation**

要求：

- `RunnerActionGate` 第一版只放行：
  - `observe_only`
  - `broadcast_update`
  - `cancel_turn`
  - `restart_subsession`
  - `rerun_current_step`
  - `mark_needs_review`
- 提供：
  - `check_allowed(action_name)`
  - `execute(action_name, *, context)`
- 第一版先只做内存级执行器，不直接落真实副作用
- 对未知动作直接拒绝

**Step 5: Run test to verify it passes**

运行同上命令。  
Expected: PASS

**Step 6: Commit**

```bash
git add services/audit_runtime/runner_action_gate.py tests/test_runner_action_gate.py
git commit -m "feat: add runner action gate"
```

---

### 任务 6：把 Observer 接进现有事件流和 Runner 播报

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/agent_runner.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/audit.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_observer_event_bridge.py`

**Step 1: Write the failing test**

```python
def test_observer_decision_is_written_to_audit_run_events(db_session):
    ...
    assert payload["event_kind"] == "runner_observer_decision"
    assert payload["meta"]["stream_layer"] == "user_facing"
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_observer_event_bridge.py
```

Expected: FAIL

**Step 3: Commit the failing test**

```bash
git add tests/test_runner_observer_event_bridge.py
git commit -m "test: add failing tests for runner observer event bridge"
```

**Step 4: Write the minimal implementation**

要求：

- 当关键事件写入时，触发一次 `ProjectRunnerObserverSession.observe(...)`
- 把结构化判断写入 `audit_run_events`
  - `event_kind = "runner_observer_decision"`
  - `meta.stream_layer = "observer_reasoning"`
- 如果判断里包含 `user_facing_broadcast`，写入：
  - `event_kind = "runner_broadcast"`
  - `meta.stream_layer = "user_facing"`
- 先只在高价值事件触发观察：
  - `runner_turn_started`
  - `provider_stream_delta`
  - `output_validation_failed`
  - `runner_turn_retrying`
  - `runner_turn_needs_review`

**Step 5: Run test to verify it passes**

运行同上命令。  
Expected: PASS

**Step 6: Commit**

```bash
git add services/audit_runtime/state_transitions.py services/audit_runtime/agent_runner.py routers/audit.py tests/test_runner_observer_event_bridge.py
git commit -m "feat: bridge runner observer decisions into events"
```

---

### 任务 7：接入真实大模型观察调用，但先只输出建议不自动做重动作

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/kimi_sdk_provider.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/providers/codex_sdk_provider.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/runner_observer_session.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_observer_llm_loop.py`

**Step 1: Write the failing test**

```python
async def test_observer_session_can_call_provider_observe_once(monkeypatch):
    ...
    assert decision.suggested_action == "observe_only"
    assert decision.user_facing_broadcast == "Runner 正在继续观察当前流程"
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_observer_llm_loop.py
```

Expected: FAIL

**Step 3: Commit the failing test**

```bash
git add tests/test_runner_observer_llm_loop.py
git commit -m "test: add failing tests for runner observer llm loop"
```

**Step 4: Write the minimal implementation**

要求：

- 为 `KimiSdkProvider` / `CodexSdkProvider` 增加 `observe_once(snapshot, memory)` 支持
- 观察调用走单独 prompt，不复用业务 JSON 产出 prompt
- 观察输出必须过 `RunnerObserverDecision` 解析
- 第一版只放行低风险动作自动执行：
  - `observe_only`
  - `broadcast_update`
- 其余动作先写建议事件，不自动执行

**Step 5: Run test to verify it passes**

运行同上命令。  
Expected: PASS

**Step 6: Commit**

```bash
git add services/audit_runtime/providers/kimi_sdk_provider.py services/audit_runtime/providers/codex_sdk_provider.py services/audit_runtime/runner_observer_session.py tests/test_runner_observer_llm_loop.py
git commit -m "feat: add llm-backed runner observer loop"
```

---

### 任务 8：把 Observer 接到项目启动和真实验收脚本

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/utils/manual_check_ai_review_flow.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_runner_observer_acceptance_metrics.py`

**Step 1: Write the failing test**

```python
from utils.manual_check_ai_review_flow import summarize_runner_metrics


def test_runner_metrics_include_observer_decision_counts():
    metrics = summarize_runner_metrics(
        [
            {"event_kind": "runner_observer_decision", "meta": {"provider_name": "sdk"}},
            {"event_kind": "runner_broadcast", "meta": {"provider_name": "sdk"}},
        ],
        requested_provider_mode="sdk",
        runtime_status={"provider_mode": "sdk"},
    )
    assert metrics["observer_decision_count"] == 1
```

**Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_runner_observer_acceptance_metrics.py
```

Expected: FAIL

**Step 3: Commit the failing test**

```bash
git add tests/test_runner_observer_acceptance_metrics.py
git commit -m "test: add failing tests for runner observer acceptance metrics"
```

**Step 4: Write the minimal implementation**

要求：

- 项目启动时初始化 `ProjectRunnerObserverSession`
- 验收脚本新增指标：
  - `observer_decision_count`
  - `observer_intervention_suggested_count`
  - `observer_auto_action_count`
  - `observer_recent_progress_assessment`
- 真实验收优先用 sdk provider
- 验收重点不是“大项目 180 秒内跑完”，而是：
  - 它是不是全程持续观察
  - 它有没有持续给出现场理解和反馈

**Step 5: Run test to verify it passes**

运行同上命令。  
Expected: PASS

**Step 6: Commit**

```bash
git add services/audit_runtime/orchestrator.py utils/manual_check_ai_review_flow.py tests/test_runner_observer_acceptance_metrics.py
git commit -m "feat: add runner observer acceptance metrics"
```

---

### 任务 9：跑完整回归并做真实项目验收

**文件：**
- 产物：`/Users/harry/@dev/ccad/.artifacts/manual-checks/<project>-runner-observer-check.json`

**Step 1: Run backend tests**

Run:
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q \
  tests/test_runner_observer_types.py \
  tests/test_runner_observer_prompt.py \
  tests/test_runner_observer_feed.py \
  tests/test_runner_observer_session.py \
  tests/test_runner_action_gate.py \
  tests/test_runner_observer_event_bridge.py \
  tests/test_runner_observer_llm_loop.py \
  tests/test_runner_observer_acceptance_metrics.py
```

Expected: PASS

**Step 2: Run existing runner regression tests**

Run:
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q \
  tests/test_runner_supervisor_state.py \
  tests/test_runner_stall_recovery.py \
  tests/test_runner_broadcasts.py \
  tests/test_runner_broadcast_event_bridge.py \
  tests/test_kimi_sdk_provider_idle_timeout.py
```

Expected: PASS

**Step 3: Run real project acceptance**

Run:
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
AUDIT_RUNNER_PROVIDER=sdk \
./venv/bin/python utils/manual_check_ai_review_flow.py \
  --project-id <project_id> \
  --base-url http://127.0.0.1:7002
```

Expected:

- 生成 `.artifacts/manual-checks/<project>-runner-observer-check.json`
- 报告里能看到：
  - `observer_decision_count > 0`
  - `runner_broadcast_count > 0`
  - `last_progress_gap_seconds` 合理
- 如果没有真实卡住样本，也要明确写：
  - `not_observed_in_live_probe_but_not_fully_eliminated`

**Step 4: Commit verification**

```bash
git add .artifacts/manual-checks/<project>-runner-observer-check.json
git commit -m "test: verify runner observer agent flow"
```

---

## 实施顺序建议

按下面 3 批执行最稳：

### 第一批

- 任务 1
- 任务 2
- 任务 3

目标：

- 先把 Observer 的数据结构、人格提示、观察面板立起来

### 第二批

- 任务 4
- 任务 5
- 任务 6

目标：

- 先打通“观察 -> 结构化判断 -> 事件写回 -> 动作闸门”

### 第三批

- 任务 7
- 任务 8
- 任务 9

目标：

- 接真实大模型观察循环
- 接真实项目验收

---

## 风险提醒

### 风险 1：观察上下文过大

不要把完整原始事件无限塞给 Runner 长会话。  
必须优先实现摘要层和介入历史层。

### 风险 2：大模型判断不稳定

第一版先允许“给建议”，只自动执行低风险动作。  
不要一开始就放开重建子会话和重跑步骤的自动执行。

### 风险 3：事件触发过于频繁

不要每条低价值事件都触发观察判断。  
先只在关键事件触发，避免又慢又贵。

### 风险 4：提示词和硬闸门职责混淆

不要把目录白名单、动作上限、禁止动作只写在 `Agent.md / soul.md` 里。  
这些必须写进 `runner_action_gate.py` 和相关执行器。

---

## 验收口径

这次验收不再用“大项目必须在 180 秒内跑完”来判断成功。

真正的验收口径是：

1. Runner Observer Agent 是否从头到尾持续在线观察
2. 它是否持续产出对现场的理解，而不是只转发事件
3. 它是否在关键时刻给出合理建议或动作
4. 普通用户是否看到的是 Runner 的播报，而不是底层 JSON 碎片
5. 如果真实探针里没有撞上静默卡住样本，也必须诚实写清：
   - 测试证据充分
   - 真实样本证据仍不足
