# 审图进度日志面板实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 为长时间运行的 AI 审图流程增加面向设计师的实时日志面板，让用户在审图弹窗中持续看到“系统正在做什么、做到哪里、是否正常推进”。

**架构：** 采用 `V1：事件表 + 轮询`。后端把审图过程中的关键动作和心跳信息写入持久化事件表；前端在现有审图弹窗右侧增加“实时进度日志”面板，通过增量轮询拉取并展示大白话日志。事件模型、接口结构与前端状态设计将预留后续流式升级空间，但本次不实现 SSE/WebSocket。

**技术栈：** FastAPI、SQLAlchemy、SQLite、React、TypeScript、Vite

---

### 任务 1：新增审核运行事件模型与查询接口

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/models.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/database.py`（如模型注册/初始化需要）
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/routers/audit.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_events_api.py`

**步骤 1：编写失败测试**

新增 API 测试，覆盖：
- 可按 `project_id + audit_version` 拉取事件
- 支持 `since_id` 增量拉取
- 返回顺序稳定
- 返回字段仅包含前端需要的展示信息和少量元信息

**步骤 2：新增数据模型**

新增 `AuditRunEvent` 表，字段建议：
- `id`
- `project_id`
- `audit_version`
- `level`：`info | success | warning | error`
- `step_key`
- `message`
- `meta_json`
- `created_at`

**步骤 3：新增查询接口**

在 `audit.py` 增加：
- `GET /api/projects/{project_id}/audit/events`

请求参数建议：
- `version`
- `since_id`
- `limit`

响应字段建议：
- `id`
- `audit_version`
- `level`
- `step_key`
- `message`
- `created_at`
- `meta`

**步骤 4：运行测试验证通过**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_audit_events_api.py
```

---

### 任务 2：为审图主流程添加大白话事件埋点

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/state_transitions.py`
- 修改：`/Users/harry/@dev/ccad/cad-review-backend/services/audit/relationship_discovery.py`
- 可能修改：`/Users/harry/@dev/ccad/cad-review-backend/services/task_planner_service.py`
- 测试：`/Users/harry/@dev/ccad/cad-review-backend/tests/test_audit_runtime_events.py`

**步骤 1：编写失败测试**

覆盖以下事件存在性：
- 审图启动
- 三线校验完成
- 图纸上下文构建开始/完成
- 跨图关系分析开始
- 跨图关系每组开始/完成/较慢/跳过
- 审核任务规划开始/完成/回退
- 索引/尺寸/材料阶段开始/完成
- 审图完成/失败

**步骤 2：增加事件写入工具**

在 `state_transitions.py` 增加统一事件写入函数，例如：
- `append_run_event(...)`

要求：
- 写数据库，不依赖 stdout
- 大白话文案在服务端生成
- 同时允许 `meta_json` 保留技术明细，但前端默认不展示

**步骤 3：在主链路埋点**

在 `orchestrator.py` 关键节点加事件：
- “开始准备审图数据”
- “图纸信息整理完成，共 X 张图纸可进入审图”
- “开始分析跨图关系”
- “开始规划审核任务”
- “开始尺寸核对”等

**步骤 4：在关系发现阶段增加细粒度事件**

在 `relationship_discovery.py` 增加批次事件，文案面向设计师：
- `正在处理第 3 组图纸，共 12 组`
- `第 3 组图纸关系分析完成，发现 4 处关联`
- `第 4 组图纸分析时间较长，系统仍在继续`
- `第 5 组图纸暂时没有得到可用结果，系统已继续后续分析`

**步骤 5：增加心跳日志**

对长耗时阶段增加定时心跳事件：
- 仅在超过阈值时写入，避免刷屏
- 建议同一步骤内至少间隔 `20-30` 秒
- 文案保持稳定、非技术化

**步骤 6：运行后端测试**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_audit_runtime_events.py tests/test_relationship_discovery.py tests/test_plan_audit_tasks_api.py
```

---

### 任务 3：前端审图弹窗右侧增加实时日志面板

**文件：**
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail.tsx`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/api/index.ts`
- 修改：`/Users/harry/@dev/ccad/cad-review-frontend/src/types/api.ts`
- 可能新增：`/Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx`

**步骤 1：定义前端类型与 API**

新增：
- `AuditEvent`
- `getAuditEvents(projectId, { version, sinceId, limit })`

**步骤 2：改造进度弹窗布局**

`AuditProgressDialog` 调整为左右双栏：
- 左侧：保留现有大标题、进度条、三阶段卡片
- 右侧：新增“实时进度日志”面板

**步骤 3：实现日志列表展示**

展示规则：
- 最新日志在底部并自动滚动
- 每条显示：
  - 状态色
  - 时间
  - 大白话消息
- 不显示技术字段

**步骤 4：在 ProjectDetail 中增加轮询**

轮询策略：
- 审图进行中每 `2s` 拉一次
- 使用 `since_id` 增量拉取
- 最多保留最近 `50` 条
- 最小化/重新打开弹窗时不丢历史

**步骤 5：处理空状态与异常状态**

示例文案：
- 空状态：`审图启动后，系统会在这里持续更新进度`
- 拉取失败：`暂时无法更新进度日志，后台仍可能在继续运行`

**步骤 6：运行前端校验**

运行：
```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm run lint
```

---

### 任务 4：文案规范与体验校准

**文件：**
- 可能新增：`/Users/harry/@dev/ccad/docs/plans/2026-03-09-audit-log-copy-guidelines.md`
- 修改：后端事件文案生成处

**步骤 1：整理日志文案规范**

文案规则：
- 用户对象是设计师，不懂代码
- 每条日志回答“正在做什么 / 做到哪里 / 是否正常”
- 禁止直接暴露 `JSON`、`batch`、`LLM`、`timeout` 等字眼

**步骤 2：统一 4 类文案风格**

- `进行中`
- `已完成`
- `需注意`
- `需要处理`

**步骤 3：人工走查**

挑一个真实项目，确认日志读起来像“项目助理在汇报进度”，而不是程序控制台。

---

### 任务 5：真实项目回归验证

**文件：**
- 使用：`/Users/harry/@dev/ccad/cad-review-backend/utils/manual_check_ai_review_flow.py`

**步骤 1：启动前后端**

确保：
- frontend `7001`
- backend `7002`

**步骤 2：选择长耗时真实项目**

至少验证一个 40+ 张图项目，观察：
- 日志是否持续更新
- 长耗时阶段是否每隔一段时间有心跳日志
- 用户能否从日志判断系统仍在工作

**步骤 3：验证页面刷新与最小化恢复**

检查：
- 重开弹窗后历史日志仍在
- 页面刷新后仍能从接口恢复最近日志

**步骤 4：验证完成态与失败态**

确认：
- 审图完成时出现收尾日志
- 失败时出现大白话错误提示

---

### 任务 6：完成前统一验证

**步骤 1：后端验证**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/pytest -q tests/test_kimi_service.py tests/test_relationship_discovery.py tests/test_master_planner_service.py tests/test_plan_audit_tasks_api.py tests/test_audit_events_api.py tests/test_audit_runtime_events.py
./venv/bin/python -m py_compile services/kimi_service.py services/audit/relationship_discovery.py services/master_planner_service.py services/audit_runtime/orchestrator.py services/audit_runtime/state_transitions.py routers/audit.py
```

**步骤 2：前端验证**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend
npm run lint
```

**步骤 3：真实项目验证**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend
./venv/bin/python utils/manual_check_ai_review_flow.py --project-id <真实项目ID> --base-url http://127.0.0.1:7002 --request-timeout 190
```
