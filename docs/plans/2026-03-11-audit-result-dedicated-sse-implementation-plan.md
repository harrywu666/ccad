# 审图结果专用 SSE（逐条出报告）实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 审图进行中就把问题一条条推到“审核报告”页面，用户可以一边看已出问题一边等后续结果，不再等整轮结束才看到报告。

**架构：** 保留现有“过程日志流”（`/audit/events/stream`）不动，新增“结果专用流”（`/audit/results/stream`）。后端在问题真正写入数据库后发 `result_upsert` 事件；前端用“追加/原地更新”策略合并，不刷新整页，不打断用户当前正在看的问题。

**技术栈：** FastAPI `StreamingResponse`、SQLAlchemy、React + TypeScript、现有 `AuditRunEvent` 事件账本

---

## 任务边界（先说清做什么/不做什么）

**做什么：**
- 新增专用结果 SSE 接口与前端订阅器
- 审图运行中实时更新左侧问题列表与统计卡片
- 保证“用户当前选中问题 + 右侧图纸对比”不被新增问题打断
- 审图结束时做一次最终全量对账，避免漏包

**不做什么：**
- 不改 WebSocket，不引入新依赖
- 不改数据库表结构（复用 `audit_run_events.meta_json`）
- 不改现有日志弹窗主流程（只新增结果流并并行使用）
- 不做无关重构

---

### 任务 1：先补“结果专用流”后端失败测试（TDD 起手）

**相关技能：** `@api-design` `@verification-before-completion`

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_results_stream_api.py`

**步骤 1：编写失败测试**

覆盖点：
- `GET /api/projects/{project_id}/audit/results/stream` 返回 `text/event-stream`
- 仅推送结果类事件（`result_upsert` / `result_summary` / `heartbeat`）
- 支持 `since_id` 续传，且 `id` 单调递增

**步骤 2：运行测试确认失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_audit_results_stream_api.py
```

预期：FAIL（接口尚不存在）

**步骤 3：提交失败测试**

```bash
git add /Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_results_stream_api.py
git commit -m "test: add failing tests for audit result dedicated sse api"
```

### 任务 2：实现后端“结果专用 SSE”接口

**相关技能：** `@api-design` `@backend-patterns`

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/audit.py`

**步骤 1：新增结果流序列化与过滤器**

实现：
- 复用 `_format_sse_event`
- 新增结果流迭代器（建议命名：`_iter_audit_results_stream`）
- 过滤 `AuditRunEvent.event_kind in {"result_upsert","result_summary","heartbeat"}`

**步骤 2：新增专用路由**

新增：
- `GET /api/projects/{project_id}/audit/results/stream?version=&since_id=`
- 响应头同日志 SSE（`Cache-Control/Connection/X-Accel-Buffering`）

**步骤 3：运行测试确认通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_audit_results_stream_api.py
```

预期：PASS

**步骤 4：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-backend/routers/audit.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_results_stream_api.py
git commit -m "feat: add dedicated sse endpoint for audit results"
```

### 任务 3：先补“写库后发结果事件”失败测试

**相关技能：** `@test-driven-development` `@backend-patterns`

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_result_event_bridge.py`

**步骤 1：编写失败测试**

覆盖点：
- 当 `AuditResult` 落库成功后，会写入 `audit_run_events`
- 事件 `event_kind == "result_upsert"`
- 事件 `meta_json` 至少包含：
  - `delta_kind: "upsert"`
  - `view: "grouped"`
  - `row`（可直接给前端渲染的结果行）
  - `counts`（总数 + 各类型未解决数）

**步骤 2：运行测试确认失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_result_event_bridge.py
```

预期：FAIL（当前没有结果事件桥接）

**步骤 3：提交失败测试**

```bash
git add /Users/harry/@dev/ccad/cad-review-backend/tests/test_result_event_bridge.py
git commit -m "test: add failing tests for result-upsert event bridge"
```

### 任务 4：实现“问题写库 -> 结果事件”桥接（核心）

**相关技能：** `@backend-patterns` `@verification-before-completion`

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/persistence.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/audit.py`（复用序列化分组函数）
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_result_event_bridge.py`

**步骤 1：在状态层新增统一发事件函数**

建议新增（示例）：

```python
def append_result_upsert_event(project_id: str, audit_version: int, *, row: dict, counts: dict) -> None:
    append_run_event(
        project_id,
        audit_version,
        level="info",
        step_key="result_stream",
        agent_key="runner_agent",
        agent_name="Runner Agent",
        event_kind="result_upsert",
        progress_hint=None,
        message="Runner 已追加一条审图问题到报告流",
        meta={"delta_kind": "upsert", "view": "grouped", "row": row, "counts": counts},
    )
```

**步骤 2：在持久化层加“落库并推送”小工具**

要求：
- 只在 `db.flush()/db.commit()` 成功后发 `result_upsert`
- 失败时不发事件，避免前端看到“幽灵问题”

**步骤 3：接入三类 Agent**

要求：
- `index/material/dimension` 都走同一桥接函数
- 保持现有业务逻辑和提示词不变，只改“落库后推送”

**步骤 4：运行测试确认通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_result_event_bridge.py tests/test_audit_results_stream_api.py
```

预期：PASS

**步骤 5：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py /Users/harry/@dev/ccad/cad-review-backend/services/audit/persistence.py /Users/harry/@dev/ccad/cad-review-backend/services/audit/index_audit.py /Users/harry/@dev/ccad/cad-review-backend/services/audit/dimension_audit.py /Users/harry/@dev/ccad/cad-review-backend/services/audit/material_audit.py /Users/harry/@dev/ccad/cad-review-backend/routers/audit.py /Users/harry/@dev/ccad/cad-review-backend/tests/test_result_event_bridge.py
git commit -m "feat: stream persisted audit findings via result_upsert events"
```

### 任务 5：先补前端“结果流控制器”失败测试

**相关技能：** `@frontend-patterns` `@test-driven-development`

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/auditResultStream.test.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/types/api.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/api/index.ts`

**步骤 1：编写失败测试**

覆盖点：
- 能接 `result_upsert` 并输出到回调
- 断线后带 `since_id` 自动重连
- 重连多次失败自动回退轮询

**步骤 2：运行测试确认失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm test -- auditResultStream.test.ts
```

预期：FAIL（控制器尚未实现）

**步骤 3：提交失败测试**

```bash
git add /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/auditResultStream.test.ts /Users/harry/@dev/ccad/cad-review-frontend/src/types/api.ts /Users/harry/@dev/ccad/cad-review-frontend/src/api/index.ts
git commit -m "test: add failing tests for dedicated audit result stream controller"
```

### 任务 6：实现前端“丝滑追加，不打断当前查看”

**相关技能：** `@frontend-patterns` `@ui-ux-pro-max`

**文件：**
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/auditResultStream.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/ProjectStepAudit.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/api/index.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/types/api.ts`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/auditResultStream.test.ts`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/ProjectStepAudit.reportState.test.ts`
- 创建：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/ProjectDetail.incrementalResults.test.tsx`

**步骤 1：接入结果专用 SSE（和日志流并行）**

要求：
- 仅在 `Step 3`（审核报告页）订阅结果流
- 运行中也显示 `ProjectStepAudit`（移除 `projectStatus === 'auditing'` 的直接 `return null`）
- 移除 `return null` 后，若当前结果列表为空，展示占位文案：
  - `审图正在进行，问题将陆续出现`
  - 占位态不显示“空白表格”，避免用户误解为“系统没在工作”

**步骤 2：实现“增量合并”策略（关键）**

规则：
- `upsert`：
  - 如果行已存在：原地更新，不改行顺序
  - 如果是新行：追加到列表尾部
- 不做整页替换，不重置滚动位置

**步骤 3：锁住用户当前查看上下文**

规则：
- 用户已经选中某条问题时，新问题到来不切换选中项
- 右侧图纸预览不自动关闭、不自动跳新问题
- 只有当前选中问题被删除时才温和提示并收起预览
- 当 `upsert` 更新了当前选中问题内容时：
  - 右侧预览做原地刷新，不收起、不跳转
  - 若 `highlight_region` 发生变化，云线重绘
  - 若仅描述/状态变化，保持当前缩放和视角

**步骤 4：运行前端测试**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm test -- auditResultStream.test.ts ProjectStepAudit.reportState.test.ts ProjectDetail.incrementalResults.test.tsx
```

预期：PASS

**步骤 5：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/auditResultStream.ts /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail.tsx /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/project-detail/ProjectStepAudit.tsx /Users/harry/@dev/ccad/cad-review-frontend/src/api/index.ts /Users/harry/@dev/ccad/cad-review-frontend/src/types/api.ts /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/auditResultStream.test.ts /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/ProjectStepAudit.reportState.test.ts /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/ProjectDetail.incrementalResults.test.tsx
git commit -m "feat: stream audit findings into report view without interrupting user focus"
```

### 任务 7：补“结束对账 + 断线兜底”验证

**相关技能：** `@verification-loop`

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/auditResultStream.ts`
- 测试：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/auditResultStream.test.ts`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_results_stream_api.py`

**步骤 1：结束态一次全量对账**

规则：
- 当 `run_status` 到 `done/failed`，触发一次 `getAuditResults(view=grouped)` 全量覆盖
- 覆盖后尝试按旧 `selectedIssueId` 恢复选中；不存在再清空

**步骤 2：断线兜底**

规则：
- SSE 重连失败后回退到短轮询结果流
- 恢复连接后自动回切 SSE

**步骤 3：运行前后端相关测试**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_audit_results_stream_api.py
cd /Users/harry/@dev/ccad/cad-review-frontend && npm test -- auditResultStream.test.ts ProjectDetail.incrementalResults.test.tsx
```

预期：PASS

**步骤 4：提交**

```bash
git add /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail.tsx /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/auditResultStream.ts /Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/__tests__/auditResultStream.test.ts /Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_results_stream_api.py
git commit -m "fix: add reconcile and reconnect fallback for result dedicated stream"
```

### 任务 8：真实验收（Test 1，SDK Provider 优先）

**相关技能：** `@verification-before-completion`

**文件：**
- 修改：`/Users/harry/@dev/ccad/docs/plans/2026-03-11-audit-result-dedicated-sse-implementation-plan.md`（补验收记录）

**步骤 1：最小自动化验证**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && ./venv/bin/pytest -q tests/test_audit_results_stream_api.py tests/test_result_event_bridge.py
cd /Users/harry/@dev/ccad/cad-review-frontend && npm test -- auditResultStream.test.ts ProjectDetail.incrementalResults.test.tsx ProjectStepAudit.reportState.test.ts
cd /Users/harry/@dev/ccad/cad-review-frontend && npm run build
```

预期：全部 PASS

**步骤 2：真实长跑验收（人工）**

验收口径（必须全满足）：
- 启动审核后 10 秒内，报告页可见并可持续增长问题条目
- 用户点开任意一条问题后，后续新增问题不会打断当前查看
- `已运行 mm:ss` 持续增长，直到任务结束
- 审图结束后总数与后端最终结果一致（无漏条、无重复）
- 页面刷新后，自动触发一次全量对账拉取（复用任务 7 的同一路径），确保已产出的增量结果可立即恢复，而不是等待 SSE 慢慢补齐

**步骤 3：记录结果并提交**

```bash
git add /Users/harry/@dev/ccad/docs/plans/2026-03-11-audit-result-dedicated-sse-implementation-plan.md
git commit -m "docs: record dedicated audit result sse acceptance checklist"
```

---

## 风险与兜底（提前说）

- 风险 1：单条问题立即落库会增加提交次数，可能影响性能  
  兜底：先保持当前批次提交策略，只保证“阶段内逐条推送”；若性能允许再切“每条即存即推”

- 风险 2：结果行分组变化导致 `id` 变化，打断选中项  
  兜底：统一使用后端 `group_id/issue_id` 作为稳定主键，前端仅原地 patch

- 风险 3：SSE 抖动造成漏包  
  兜底：`since_id` 重连 + 结束态全量对账双保险

---

## 最终交付标准（Definition of Done）

- 有独立结果 SSE：`/api/projects/{project_id}/audit/results/stream`
- 运行中报告页可持续追加问题，不需等整轮结束
- 用户当前查看不会被新增问题打断
- 断线可续，结束可对账
- 自动化测试 + 真实 `test1` 长跑验收都有证据
