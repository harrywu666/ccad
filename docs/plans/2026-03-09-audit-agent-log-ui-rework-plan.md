# 审图等待界面与 Agent 日志流重构 实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 把“启动审核”后的等待界面改成 Agent 视角，并把当前卡片式事件列表重构成真正的流式日志面板。

**架构：** 后端继续以持久化事件流为基础，但补充 `agent_key / agent_name / event_kind / progress_hint` 等结构化字段；前端把现有弹窗改成“主状态区 + 流式日志区”，日志按 Agent 连续输出、自动滚动、合并心跳，不再使用重卡片列表。整套改造以轮询为基础实现流式感，不引入 WebSocket。

**技术栈：** FastAPI、SQLAlchemy、React、Vite、TypeScript、Radix Dialog、现有 `AuditRunEvent` 持久化机制

---

### 任务 1：补齐事件模型的 Agent 语义

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/models.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/database.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_runtime_events.py`

**步骤 1：编写失败的测试**

在 `test_audit_runtime_events.py` 新增断言，要求新写入的事件包含：
- `agent_key`
- `agent_name`
- `event_kind`
- `progress_hint`

**步骤 2：运行测试验证它失败**

运行：`./venv/bin/pytest -q tests/test_audit_runtime_events.py -k agent`

预期：FAIL，提示缺少新字段或 API 响应中没有这些字段。

**步骤 3：编写最小实现**

- 在 `AuditRunEvent` 表中新增字段：
  - `agent_key`
  - `agent_name`
  - `event_kind`
  - `progress_hint`
- 在 `database.py` 的轻量迁移逻辑里补列
- 扩展 `append_run_event(...)` 签名，支持新字段写入

**步骤 4：运行测试验证它通过**

运行：`./venv/bin/pytest -q tests/test_audit_runtime_events.py`

预期：PASS

**步骤 5：提交**

```bash
git add cad-review-backend/models.py cad-review-backend/database.py cad-review-backend/services/audit_runtime/state_transitions.py cad-review-backend/tests/test_audit_runtime_events.py
git commit -m "feat: add agent metadata to audit runtime events"
```

### 任务 2：把现有审图事件改写成 Agent 视角文案

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_runtime_events.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_index_worker_ai_review.py`

**步骤 1：编写失败的测试**

新增断言，要求主流程与各 worker 输出的是 Agent 文案，例如：
- `总控规划Agent`
- `关系审查Agent`
- `索引审查Agent`
- `尺寸审查Agent`
- `材料审查Agent`

并明确 `event_kind` 取值，例如：
- `phase_started`
- `phase_progress`
- `phase_completed`
- `heartbeat`
- `warning`

**步骤 2：运行测试验证它失败**

运行：`./venv/bin/pytest -q tests/test_audit_runtime_events.py tests/test_index_worker_ai_review.py`

预期：FAIL，当前事件没有 Agent 元信息或文案仍是旧阶段语义。

**步骤 3：编写最小实现**

- 在 orchestrator 和各审查模块里统一改写 `append_run_event(...)`
- 明确每个模块的 `agent_key / agent_name`
- 把现有文案改成大白话且 Agent 视角
- 索引 AI 复核补日志：
  - 发现高歧义索引
  - 正在做 AI 复核
  - 复核后保留/去除

**步骤 4：运行测试验证它通过**

运行：`./venv/bin/pytest -q tests/test_audit_runtime_events.py tests/test_index_worker_ai_review.py`

预期：PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/services/audit/relationship_discovery.py cad-review-backend/services/audit/index_audit.py cad-review-backend/services/audit/dimension_audit.py cad-review-backend/services/audit/material_audit.py cad-review-backend/tests/test_audit_runtime_events.py cad-review-backend/tests/test_index_worker_ai_review.py
git commit -m "feat: emit audit runtime logs from agent perspective"
```

### 任务 3：补心跳事件和重复日志合并策略

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_runtime_events.py`

**步骤 1：编写失败的测试**

新增测试覆盖：
- 长耗时阶段会定期写 `heartbeat`
- 同类心跳不会无限刷屏，而是带可合并字段（例如 `coalesce_key` 或稳定 `event_kind + meta`）

**步骤 2：运行测试验证它失败**

运行：`./venv/bin/pytest -q tests/test_audit_runtime_events.py -k heartbeat`

预期：FAIL

**步骤 3：编写最小实现**

- 为长耗时阶段增加心跳写入
- 心跳 `meta` 中至少包含：
  - `group_index`
  - `group_total`
  - `elapsed_seconds`
  - `coalesce_key`
- 保持持久化事件语义，但让前端有能力把心跳合并成“同一行动态更新”

**步骤 4：运行测试验证它通过**

运行：`./venv/bin/pytest -q tests/test_audit_runtime_events.py`

预期：PASS

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/state_transitions.py cad-review-backend/services/audit/relationship_discovery.py cad-review-backend/services/audit/dimension_audit.py cad-review-backend/tests/test_audit_runtime_events.py
git commit -m "feat: add heartbeat-friendly audit runtime events"
```

### 任务 4：扩展前端事件类型与轮询消费模型

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/types/api.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/api/index.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail.tsx`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/...`（如项目已有前端测试基础）

**步骤 1：编写失败的测试**

如果现有前端测试基础可用，则新增：
- 事件类型支持 `agent_key / agent_name / event_kind / progress_hint`
- 轮询时同类心跳按 `coalesce_key` 合并，而不是无限 append

如果没有现成测试基础，则记录为本任务的验证命令和手工验收项。

**步骤 2：运行测试验证它失败**

运行前端测试或类型检查。

预期：FAIL 或类型缺失。

**步骤 3：编写最小实现**

- 更新 `AuditEvent` 前端类型
- 在 `ProjectDetail.tsx` 的事件轮询逻辑里做增量合并
- 为心跳事件增加“替换最后一条同 key 日志”的能力

**步骤 4：运行测试验证它通过**

运行前端测试或 `npm run lint`

预期：PASS

**步骤 5：提交**

```bash
git add cad-review-frontend/src/types/api.ts cad-review-frontend/src/api/index.ts cad-review-frontend/src/pages/ProjectDetail.tsx
git commit -m "feat: support agent log stream event model in frontend"
```

### 任务 5：重做等待弹窗主状态区

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx`

**步骤 1：编写失败的测试**

若前端测试基础可用，新增断言：
- 弹窗头部显示当前 Agent
- 显示当前动作说明
- 显示下一步预告/辅助说明
- 不再把右侧日志面板挤压主卡片尺寸

**步骤 2：运行测试验证它失败**

运行前端测试或截图比对流程。

预期：FAIL

**步骤 3：编写最小实现**

- 主卡片仍保持当前主要尺寸
- 左侧主状态区改成 Agent 视角：
  - 当前 Agent
  - 当前动作
  - 进度
  - 下一步
- 保持“最小化 / 关闭”操作不变

**步骤 4：运行测试验证它通过**

运行：`npm run lint`

预期：PASS

**步骤 5：提交**

```bash
git add cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx
git commit -m "feat: redesign audit waiting dialog around agent status"
```

### 任务 6：把右侧日志区改成流式控制台样式

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx`
- 可选创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditEventStreamLine.tsx`

**步骤 1：编写失败的测试**

新增断言或手工验收项：
- 日志是一行一条，而不是重卡片
- 默认自动滚动到底部
- 用户手动上滚时暂停自动滚动
- 新日志继续流式 append

**步骤 2：运行测试验证它失败**

运行前端测试或实际页面检查。

预期：FAIL

**步骤 3：编写最小实现**

- 改成“控制台流”式布局
- 使用更轻的行级样式：
  - 时间
  - Agent 标签
  - 状态标签
  - 文案
- 支持：
  - 自动滚动
  - 暂停自动滚动
  - `全部 / 仅关键节点 / 仅异常` 过滤

**步骤 4：运行测试验证它通过**

运行：`npm run lint`

预期：PASS

**步骤 5：提交**

```bash
git add cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx
git commit -m "feat: turn audit event panel into streaming log view"
```

### 任务 7：统一日志文案规范并补回归截图/人工验收

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/utils/manual_check_ai_review_flow.py`
- 文档：`/Users/harry/@dev/ccad/docs/plans/2026-03-09-audit-agent-log-ui-rework-plan.md`

**步骤 1：编写失败的测试**

补一个轻量回归：
- 抽样断言日志文案不包含明显技术术语，例如：
  - `LLM`
  - `JSON parse`
  - `batch`
  - `timeout`

必要时允许在 `meta` 里保留技术细节，但 UI 文案不能暴露给设计师。

**步骤 2：运行测试验证它失败**

运行后端日志测试。

预期：FAIL

**步骤 3：编写最小实现**

- 清理剩余技术化文案
- 手工验收脚本增加日志抽样输出
- 验收等待界面：
  - 日志连续
  - 文案大白话
  - Agent 视角明确

**步骤 4：运行测试验证它通过**

运行：
- `./venv/bin/pytest -q tests/test_audit_runtime_events.py tests/test_index_worker_ai_review.py`
- `npm run lint`
- 手工验收脚本 / 实际页面验证

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/services/audit/relationship_discovery.py cad-review-backend/services/audit/index_audit.py cad-review-backend/services/audit/dimension_audit.py cad-review-backend/services/audit/material_audit.py cad-review-backend/utils/manual_check_ai_review_flow.py docs/plans/2026-03-09-audit-agent-log-ui-rework-plan.md
git commit -m "refactor: align audit runtime logs with agent-based UX"
```

### 任务 8：整体验证

**文件：**
- 验证：`/Users/harry/@dev/ccad/cad-review-backend/tests/...`
- 验证：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/...`

**步骤 1：运行后端回归**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q \
  tests/test_audit_runtime_events.py \
  tests/test_index_worker_ai_review.py \
  tests/test_plan_audit_tasks_api.py \
  tests/test_audit_orchestrator_flags.py
```

预期：PASS，无 warning 或仅保留已知三方库 warning。

**步骤 2：运行前端验证**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm run lint
```

预期：PASS

**步骤 3：运行人工验收**

使用真实项目手工检查：
- 启动审核后等待弹窗保持原主卡片尺寸
- 右侧日志区表现为连续流，不是大卡片堆叠
- 能看到 Agent 名称
- 长耗时阶段能持续刷新，而不是停在静态阶段卡上

**步骤 4：提交**

```bash
git add .
git commit -m "test: validate agent-based waiting UI and streaming audit logs"
```
