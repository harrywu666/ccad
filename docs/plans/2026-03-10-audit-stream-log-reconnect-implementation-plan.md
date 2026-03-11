# 审图真流式输出与断线重连 实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 把 Kimi 的真实流式输出接进后端，再把这条流实时推给前端，并支持上下游断线自动续上。

**架构：** 先重构 `kimi_service.py`，新增 `call_kimi_stream()` 接官方流式输出；后端把模型流片段和阶段事件统一写入 `audit_run_events`；前端优先使用 SSE 接这条事件流，失败时自动回退到轮询。上下游都支持自动重试和断线重连。

**技术栈：** FastAPI、SSE（`text/event-stream`）、React、Moonshot/Kimi 官方流式输出、现有事件轮询接口

---

### 任务 1：补齐当前真流式方案涉及的现状调研

**文件：**
- 修改：`/Users/harry/@dev/ccad/docs/plans/2026-03-10-audit-stream-log-reconnect-design.md`

**步骤 1：确认当前 Kimi 调用口、后端事件接口和前端日志面板边界**

运行：

```bash
rg -n "call_kimi|audit/events|AuditEventList|AuditProgressDialog" /Users/harry/@dev/ccad/cad-review-backend /Users/harry/@dev/ccad/cad-review-frontend
```

预期：能定位 Kimi 服务入口、后端事件查询接口和前端日志渲染入口。

**步骤 2：把当前接口限制写进设计文档**

补充现状：

- 当前只有轮询
- 当前已有 `since_id`
- 当前已有 `agent_name / event_kind / progress_hint`

**步骤 3：提交**

```bash
git add /Users/harry/@dev/ccad/docs/plans/2026-03-10-audit-stream-log-reconnect-design.md
git commit -m "docs: refine audit stream reconnect design context"
```

### 任务 2：先写 Kimi 流式服务层测试

**文件：**
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_kimi_stream_service.py`

**步骤 1：编写失败测试**

覆盖点：

- 能逐段接收 Kimi 返回
- 遇到 `429` 能自动等待并重试
- 遇到临时断开能重连
- 最终仍能拼出完整文本

**步骤 2：运行测试确认失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_kimi_stream_service.py
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add /Users/harry/@dev/ccad/cad-review-backend/tests/test_kimi_stream_service.py
git commit -m "test: add failing tests for kimi stream service"
```

### 任务 3：实现 `call_kimi_stream()` 和上游自动重连

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/kimi_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_kimi_stream_service.py`

**步骤 1：新增流式调用入口**

实现：

- `call_kimi_stream()`
- 保留 `call_kimi()` 兼容旧路径

**步骤 2：加入上游自动重连**

要求：

- `429` 自动等待重试
- `5xx` 自动退避重试
- 流中断时可重建连接
- 把重试行为写入日志

**步骤 3：运行测试确认通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_kimi_stream_service.py
```

预期：PASS

**步骤 4：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-backend/services/kimi_service.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_kimi_stream_service.py
git commit -m "feat: add kimi streaming service with reconnect support"
```

### 任务 4：让总控规划Agent先接入真流式

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/master_planner_service.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_master_planner_stream.py`

**步骤 1：编写失败测试**

覆盖点：

- plan 阶段确实走了 `call_kimi_stream()`
- 能产出 `model_stream_delta` 事件
- 重试信息会写进阶段事件

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_master_planner_stream.py
```

预期：FAIL

**步骤 2：把 plan 阶段切到 `call_kimi_stream()`**

要求：

- 一边接流，一边写事件
- 事件里区分：
  - `model_stream_delta`
  - `phase_event`

**步骤 3：把重试和断流信息写进事件流**

至少能看见：

- 正在等待 Kimi 返回
- 第几次重试
- 因为什么重试

**步骤 4：运行测试确认通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_master_planner_stream.py
```

预期：PASS

**步骤 5：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-backend/services/master_planner_service.py /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_master_planner_stream.py
git commit -m "feat: stream planner output into audit events"
```

### 任务 5：补后端 SSE 接口测试

**文件：**
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_events_stream_api.py`

**步骤 1：编写失败测试**

覆盖点：

- 可返回 `text/event-stream`
- 能先补 `since_id` 之后的历史事件
- 能推送 `model_stream_delta`
- 没新事件时能发心跳
- 事件格式里包含 `id`

**步骤 2：运行测试确认失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_audit_events_stream_api.py
```

预期：FAIL

### 任务 6：实现后端 SSE 日志流接口

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/audit.py`

**步骤 1：新增 SSE 路由**

新增接口：

- `GET /api/projects/{project_id}/audit/events/stream`

支持参数：

- `version`
- `since_id`

**步骤 2：实现推送规则**

行为要求：

- 先推历史
- 再等待新增事件
- 没有新增时按 `25` 秒固定间隔发送心跳事件
- 能把 `model_stream_delta` 和普通阶段事件一起推给前端

**步骤 3：运行测试确认通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_audit_events_stream_api.py
```

预期：PASS

**步骤 4：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-backend/routers/audit.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_events_stream_api.py
git commit -m "feat: add sse stream endpoint for audit events"
```

### 任务 7：补前端 SSE 数据层测试

**文件：**
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/auditEventStream.test.ts`

**步骤 1：编写失败测试**

覆盖点：

- 正常接收 SSE 事件并追加
- 断线后带 `lastEventId` 重连
- 多次失败后回退轮询
- 能区分普通阶段事件和模型流片段
- `renders model_stream_delta in process view`
- `pauses auto-scroll when user scrolls up`
- `does not show raw model output in default view`

**步骤 2：运行测试确认失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm test -- auditEventStream
```

预期：FAIL

**步骤 3：提交失败测试**

```bash
git add /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/auditEventStream.test.ts
git commit -m "test: add failing tests for audit event streaming"
```

### 任务 8：实现前端 SSE 连接层

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/api/index.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail.tsx`
- 可创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/hooks/useAuditEventStream.ts`

**步骤 1：新增前端流式连接 Hook**

要求：

- 优先连接 SSE
- 维护 `lastEventId`
- 支持断线自动重连
- 能实时接收模型流片段

**步骤 2：加入轮询兜底**

规则：

- 连续多次重连失败后，切到现有轮询接口
- 页面状态里标记“兼容模式”

**步骤 3：运行测试确认通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm test -- auditEventStream
```

预期：PASS

**步骤 4：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-frontend/src/api/index.ts /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail.tsx /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/hooks/useAuditEventStream.ts /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/auditEventStream.test.ts
git commit -m "feat: add frontend audit event stream with reconnect fallback"
```

### 任务 9：重做日志窗口，让“阶段流”和“模型流”都能看

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/auditEventStream.test.ts`

**步骤 1：默认展示大白话阶段流**

要求：

- 普通用户一眼能看懂
- 继续保留 Agent 视角

**步骤 2：增加“模型过程”视图**

要求：

- 能看到 Kimi 流式片段
- 重点用于 plan 阶段和 AI 复核阶段
- 不把普通视图搞得太吓人

**步骤 3：补断线提示**

大白话提示至少包括：

- 正在实时连接
- 连接刚断开，正在重连
- 已切换到兼容模式

**步骤 4：保留现在的大白话 Agent 文案**

不要把 UI 退回技术术语。

**步骤 5：运行测试确认通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm test -- auditEventStream
```

预期：PASS

**步骤 6：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/auditEventStream.test.ts
git commit -m "feat: add dual-view audit stream log experience"
```

### 任务 10：为断线重连补人工兜底验证

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/utils/manual_check_ai_review_flow.py`
- 文档：`/Users/harry/@dev/ccad/docs/plans/2026-03-10-audit-stream-log-reconnect-design.md`

**步骤 1：在人工验收脚本里加真流式探活检查**

至少检查：

- Kimi 流式调用是否启动
- SSE 接口可连通
- 首包是否返回
- 心跳是否出现（`25` 秒）

**步骤 2：补“上游重试 + 下游恢复”的人工验收步骤**

写清楚：

- 模拟上游 `429/5xx`
- 是否自动等待和重试
- 断开浏览器网络
- 恢复网络
- 日志是否续上

### 任务 11：全量验证

**文件：**
- 测试：已有后端/前端测试

**步骤 1：后端测试**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_kimi_stream_service.py tests/test_master_planner_stream.py tests/test_audit_events_api.py tests/test_audit_events_stream_api.py
```

预期：PASS

**步骤 2：前端测试**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm test -- auditEventStream FindingStatusBadge
```

预期：PASS

**步骤 3：前端静态验证**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm run lint && npm run build
```

预期：PASS

**步骤 4：真实项目人工验收**

要求：

- plan 阶段能看到 Kimi 真实流式输出
- 上游断开后会自动重试
- 断线恢复后不丢中间事件
- SSE 失败时能自动退回轮询

### 任务 12：收尾记录

**文件：**
- 修改：`/Users/harry/@dev/ccad/docs/plans/2026-03-10-audit-stream-log-reconnect-design.md`
- 修改：`/Users/harry/@dev/ccad/docs/plans/2026-03-10-audit-stream-log-reconnect-implementation-plan.md`

**步骤 1：回填真实项目验收结果**

记录：

- 是否流式稳定
- 是否真的看到了 Kimi 中间输出
- 是否出现上游重试
- 是否出现重连
- 是否触发轮询兜底

**步骤 2：提交**

```bash
git add /Users/harry/@dev/ccad/docs/plans/2026-03-10-audit-stream-log-reconnect-design.md /Users/harry/@dev/ccad/docs/plans/2026-03-10-audit-stream-log-reconnect-implementation-plan.md
git commit -m "docs: add audit stream reconnect plan"
```
