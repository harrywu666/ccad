# 审图进度展示弹窗设计方案

## 先说结论

本方案方向是对的，但建议按“两步走”落地：

1. 第一版先把“看不懂进度”这个核心问题解决掉：补齐 7 个阶段的可视化、把日志改成用户看得懂的时间轴、增强最小化胶囊。
2. 第二版再补“更好看”的部分：预计剩余时间、统计仪表盘、完成动画、更多动效。

这样做的好处是改动更稳，验证更容易，也能避免一次性重构太多导致弹窗、胶囊、父页面状态不一致。

## 适用边界

本方案只讨论审图中的“进度弹窗”体验优化，不包含以下内容：

- 不改审图后端主流程
- 不改 SSE / 轮询通信机制
- 不改审图报告页
- 不改项目主页面其他步骤

---

## 一、当前审图流程全貌

### 后端流水线（orchestrator.py）

用户点击「开始审图」后，后端启动一个后台线程执行 [execute_pipeline](file:///Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py#136-152)，7 个阶段按序执行：

| 阶段 | step_key | agent_name | 进度范围 | 核心动作 |
|------|----------|------------|---------|---------|
| 1. 数据准备 | `prepare` | 总控规划Agent | 5–8% | 校验三线匹配，整理基础数据 |
| 2. 上下文构建 | `context` | 总控规划Agent | 10–11% | 调用 `build_sheet_contexts`，为每张图纸生成结构化上下文 |
| 3. 关系分析 | `relationship_discovery` | 关系审查Agent | 12–16% | 分析跨图引用和关联关系 |
| 4. 任务规划 | `task_planning` | 总控规划Agent | 18–20% | 生成审核任务图（index / dimension / material 三类任务） |
| 5. 索引核对 | [index](file:///Users/harry/@dev/ccad/cad-review-backend/services/audit_service.py#342-363) | 索引审查Agent | 20–N% | 检查断链、反向缺失、孤立索引 |
| 6. 尺寸核对 | [dimension](file:///Users/harry/@dev/ccad/cad-review-backend/services/audit_service.py#589-599) | 尺寸审查Agent | N–M% | 跨图尺寸一致性比对 |
| 7. 材料核对 | [material](file:///Users/harry/@dev/ccad/cad-review-backend/services/audit_service.py#601-611) | 材料审查Agent | M–100% | 材料信息一致性检查 |

> 进度 20%–100% 由 `progress_by_task(completed, total)` 按任务完成数线性分配。

### 事件推送机制

- 每个阶段的开始/完成/异常通过 [AuditRunEvent](file:///Users/harry/@dev/ccad/cad-review-backend/routers/audit.py#121-133) 表记录
- 事件字段包括：`step_key`、`agent_key`、`agent_name`、`event_kind`（`phase_started`/`phase_progress`/`phase_completed`/`warning`/[error](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/auditEventStream.ts#178-189)/`runner_broadcast`/`heartbeat`）、`progress_hint`、`message`、`meta`（JSON，含 issues 数、budget_usage 等）
- 前端通过 SSE 流 `GET /audit/events/stream` 实时拉取，降级为轮询 `GET /audit/events`

### 前端当前组件

| 组件 | 作用 | 现状 |
|------|------|------|
| [AuditProgressDialog.tsx](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx) | 审图进度弹窗 | 含顶部标题+进度条+3个 phase 卡片（索引/尺寸/材料） |
| [AuditEventList.tsx](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx) | 右侧终端风格日志流 | 暗色终端面板，stream/model 双视图 |
| [AuditProgressPill](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx#111-132) | 最小化后的浮动胶囊 | 显示"审核中 xx%" |
| [auditEventStream.ts](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/auditEventStream.ts) | SSE/轮询双通道控制器 | 自动重连+降级 |
| [AuditStepper.tsx](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditStepper.tsx) | 顶部三步引导条 | 目录确认 → 图纸管理 → 审核报告 |

### 当前实现上的一个注意点

当前弹窗里展示的阶段标题和 3 段状态，并不是都在弹窗组件内部算的，父页面 [ProjectDetail.tsx](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail.tsx#737) 也在参与计算。  
所以如果要改成 7 段流水线，建议把“阶段状态计算”抽成独立逻辑，避免弹窗、胶囊、父页面各算各的。

---

## 二、现有方案的不足

1. **进度不透明**：3 个 phase 卡片只体现"索引/尺寸/材料"三大步，但前面的准备、上下文、关系分析、任务规划共 4 步（占 0–20%）被"淹没"在进度条里，用户看到进度只涨到 5%–20% 时完全不知道在做什么
2. **等待体验枯燥**：只有一根进度条 + 一段文字 + 右侧终端日志，缺乏视觉吸引力和交互趣味
3. **事件日志纯技术向**：[AuditEventList](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx#130-286) 是终端风格，普通用户难以理解
4. **缺乏预估时间**：用户无法知道大概还要等多久
5. **阶段间无过渡动效**：阶段切换是瞬间跳变，没有流畅感

---

## 三、推荐落地方式

### 方案选择

这里有 3 种做法：

#### 方案 A：一次性大改

- 直接重做弹窗布局、日志面板、统计卡、动效
- 优点：视觉变化最大
- 风险：改动面太大，联动点多，容易出现状态不一致

#### 方案 B：分两版落地（推荐）

- 第一版先做 7 阶段流水线、用户版时间轴、胶囊增强
- 第二版再补预计剩余时间、统计卡、完成动画
- 优点：更稳，验证简单，出问题也好回退

#### 方案 C：只改文案和日志皮肤

- 保留原布局，只把文字和日志样式换掉
- 优点：最省事
- 缺点：核心问题没彻底解决，用户还是看不清完整进度

### 推荐结论

推荐用方案 B。  
原因很简单：先把“用户能不能看懂”做好，再补“好不好看”。这样更符合现在项目的节奏。

---

## 四、新版审图进度弹窗方案

### 设计理念

> **让等待变成"观看 AI 工作"的过程**——可视化每个 Agent 的工作状态，让用户清晰感知系统在做什么、做了多少、还剩多少。

### 4.1 第一版目标

第一版只解决 3 个问题：

1. 用户知道现在跑到哪一步了
2. 用户能看懂最近发生了什么
3. 最小化后还能快速知道当前状态

第一版先不追求花哨动效，也不强求每个数字都完美实时。

### 4.2 整体布局

```
┌──────────────────────────────────────────────────────────┐
│  顶部信息栏                                                │
│  ┌──────────────────────────────────────────────────────┐ │
│  │ AI 正在帮你审图  │  引擎: Kimi SDK  │  已运行 03:42 │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                          │
│  ┌──────────────── 主内容区 ────────────────────────────┐ │
│  │                                                      │ │
│  │  ┌─── 流水线可视化（核心区域） ────────────────────┐  │ │
│  │  │                                                │  │ │
│  │  │  1. 数据准备 -> 2. 上下文 -> 3. 关系分析 ->    │  │ │
│  │  │  4. 任务规划 -> 5. 索引核对 -> 6. 尺寸核对 ->  │  │ │
│  │  │  7. 材料核对 -> 完成                            │  │ │
│  │  │                                                │  │ │
│  │  └────────────────────────────────────────────────┘  │ │
│  │                                                      │ │
│  │  ┌─── 实时动态面板 ─────┐  ┌─── 状态摘要区 ─────┐   │ │
│  │  │ Agent 时间轴卡片      │  │ 已发现问题: 12     │   │ │
│  │  │ （最新几条关键消息）  │  │ 当前阶段: 尺寸核对 │   │ │
│  │  │                      │  │ 已运行: 03:42      │   │ │
│  │  └──────────────────────┘  └────────────────────┘   │ │
│  │                                                      │ │
│  └──────────────────────────────────────────────────────┘ │
│                                                          │
│  底部操作栏: [最小化] [中断审图]                            │
└──────────────────────────────────────────────────────────┘
```

### 4.3 各模块详细说明

#### 模块 A：流水线可视化（Pipeline Visualization）

**描述**：将后端 7 个阶段横向排列为"节点 + 连线"的流水线图，每个节点显示：
- Agent 图标
- 阶段名称
- 状态标识（待执行 → 进行中 → 已完成）
- 进行中节点有呼吸动画/脉冲效果
- 已完成节点显示完成标识和该阶段发现的问题数
- 连线可以有轻微动态效果，但第一版不强求复杂动画

**数据来源**：每收到 SSE 事件，根据 `step_key + event_kind` 更新对应节点状态：
- `phase_started` → 节点变为"进行中"
- `phase_completed` → 节点变为"已完成"，从 `meta.issues` 提取问题数
- `phase_progress` → 更新节点内子进度

**节点定义**（7 个，映射后端 step_key）：

| 前端节点 | step_key | 图标 | 说明 |
|---------|----------|------|------|
| 数据准备 | `prepare` | Database | 校验三线匹配 |
| 上下文构建 | `context` | FileText | 整理图纸结构化信息 |
| 关系分析 | `relationship_discovery` | Link2 | 分析跨图关联 |
| 任务规划 | `task_planning` | Map | 生成审核任务图 |
| 索引核对 | [index](file:///Users/harry/@dev/ccad/cad-review-backend/services/audit_service.py#342-363) | Ruler | 检测索引断链和缺失 |
| 尺寸核对 | [dimension](file:///Users/harry/@dev/ccad/cad-review-backend/services/audit_service.py#589-599) | Scale | 跨图尺寸一致性 |
| 材料核对 | [material](file:///Users/harry/@dev/ccad/cad-review-backend/services/audit_service.py#601-611) | Boxes | 材料信息一致性 |

**布局建议**：

- 宽屏下优先横向展示 7 个节点
- 中等宽度改成两行
- 小屏允许横向滚动，不强行压缩到一行

这样更符合当前弹窗宽度，避免节点挤成一团。

#### 模块 B：Agent 实时工作台（替代原有右侧 Terminal 弹窗）

**现状痛点**：原 [AuditEventList.tsx](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx) 采用 Terminal（终端）风格，存在信息密度过高、视觉层级平庸、面向开发者而非业务人员的问题。
**改进目标**：把冰冷的“纯文本终端日志”转化为更拟人化、具有清晰层级和明确状态指示的**动态进程时间轴（Activity Feed）**。

**详细设计建议**：

1. **默认改成用户版时间轴**
   - 移除原有的 `terminal://audit-stream` 标题和纯终端表达。
   - 默认展示清爽的时间轴卡片，直接说大白话。

2. **给不同 Agent 固定图标和颜色**
   - 总控规划Agent
   - 关系审查Agent
   - 索引审查Agent
   - 尺寸审查Agent
   - 材料审查Agent
   - 每条消息左侧显示对应图标，让用户一眼看出是谁在处理。

3. **事件分层展示，减少刷屏感**
   - 关键节点：开始、完成、报错，用大卡片显示
   - 普通进度：放成小字说明
   - 心跳和重复重试：合并显示，不每条都单独刷出来

4. **保留开发者模式，但默认隐藏**
   - 默认只给普通用户看整理后的进度播报
   - 右上角保留一个开关，需要时再看底层流式日志

这里不建议直接删掉开发者视图，因为它对排查卡顿、断流、重试仍然有用。

**数据流转**：继续消费 SSE 事件的 `message` 与 `meta` 数据结构，原有后端不需要做任何变动。仅做视图层次的结构重构和数据提取展示。

#### 模块 C：状态摘要区（第一版）

第一版建议先做“状态摘要区”，不要急着上复杂仪表盘。

| 指标 | 数据来源 | 第一版展示建议 |
|------|---------|---------------|
| 当前进度 | `AuditStatus.progress` 或最新事件的 `progress_hint` | 百分比 + 进度条 |
| 已发现问题 | `AuditStatus.total_issues` 或事件 `meta.issues` | 数字 |
| 当前阶段 | 最新阶段或 `current_step` | 文案 |
| 当前 Agent | 最新事件的 `agent_name` | 名称 |
| 已运行时间 | `started_at` | 时长 |

#### 模块 D：统计仪表盘（第二版可选）

第二版如果需要再补这些内容：

- 圆形进度环
- 趋势数字动画
- 更细的任务统计
- 预计剩余时间

其中有 2 个指标要特别注意：

1. **已检查图纸**
   现有事件里有时是图纸数，有时是任务数，口径不完全统一。第一版不建议直接写成固定的 `x / y 图纸`。

2. **预计剩余时间**
   前 20% 的准备阶段波动很大，线性估算容易忽高忽低。建议第二版再做，或者在任务阶段后才开始显示。

#### 模块 E：底部操作栏

- **最小化按钮**：缩为 Pill 浮窗（已有 [AuditProgressPill](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx#111-132)），保留现有逻辑
- **中断审图按钮**：显示确认对话框（已有，保留）

### 4.4 最小化后的胶囊增强

当前胶囊只显示"审核中 xx%"，建议增强为：
- 显示当前 Agent 名称（如"尺寸审查Agent 45%"）
- 已发现问题数
- 轻微脉冲动效

### 4.5 审图完成后的过渡

- 流水线全部进入完成态
- 状态摘要区定格最终数值
- 自动切换到"查看审图报告"的入口按钮
- 可以在 2 秒后给一个轻提示 toast

第一版不需要做复杂庆祝动画，避免喧宾夺主。

### 4.6 错误和中断状态

- 某个节点失败 → 该节点变红，后续节点变灰
- 用户中断 → 流水线当前节点显示黄色"已中断"
- 错误消息在 Agent 动态面板中以红色卡片展示

---

## 五、数据口径与风险说明

大方向上，这个方案可以先按前端实现推进，但有 3 个口径风险需要提前写清楚：

1. **上下文阶段的 ready 数当前口径有偏差**
   - [orchestrator.py](file:///Users/harry/@dev/ccad/cad-review-backend/services/audit_runtime/orchestrator.py#283-293) 读取的是 `context_summary.ready`
   - 但 [context_service.py](file:///Users/harry/@dev/ccad/cad-review-backend/services/context_service.py#382-385) 实际返回的是 `ready_contexts`
   - 这会导致“当前有多少张图可继续分析”的数字可能不准

2. **图纸数和任务数混用**
   - `prepare` 阶段偏图纸数
   - `task_planning` 之后偏任务数
   - 所以“已检查图纸 x / y”这个说法不能直接全程通用

3. **预计剩余时间不稳定**
   - 前半段阶段短且抖动大
   - 如果强行线性估算，数字容易来回跳

### 后端改动建议

如果只做第一版界面，原则上可以不改后端。  
但如果后面要把数字做准，建议补 1 个很小的后端修正：

- 修正 `context` 阶段完成消息里的 ready 数读取口径

这个改动很小，但能避免前端展示错误数字。

---

## 六、前端改动范围

> [!IMPORTANT]
> 本方案只列计划、不改代码，待确认后再进入实施。

### 第一版改动范围

| 文件 | 改动方式 | 说明 |
|------|---------|------|
| [ProjectDetail.tsx](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail.tsx) | 中等改动 | 抽出阶段标题和阶段状态的统一计算逻辑 |
| [AuditProgressDialog.tsx](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx) | 大幅重构 | 替换当前进度条 + 3 卡片布局为 7 阶段流水线 + 状态摘要区 |
| [AuditEventList.tsx](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx) | 中等重构 | 默认改成用户版时间轴，同时保留开发者视图开关 |
| [AuditProgressPill](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx#111-132) | 小幅增强 | 增加 Agent 名称和问题数 |
| [auditEventStream.ts](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/auditEventStream.ts) | 原则上不改 | 继续沿用现有 SSE / 轮询逻辑，只负责事件收发，不负责状态归纳 |
| `useAuditProgressViewModel.ts` | 新增 | 作为唯一的阶段状态计算出口，统一整理阶段状态、当前 Agent、摘要信息 |

### 第二版可选改动范围

| 文件 | 改动方式 | 说明 |
|------|---------|------|
| `LiveStatsDashboard.tsx` | 新增 | 真正的统计仪表盘 |
| [AuditProgressDialog.tsx](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx) | 持续增强 | 完成动效、预计时间、更多视觉细节 |

### 新增组件

| 组件名 | 功能 |
|--------|------|
| `PipelineVisualization.tsx` | 流水线可视化（7 节点 + 连线） |
| `AgentFeedPanel.tsx` | 用户版时间轴消息面板 |
| `useAuditProgressViewModel.ts` | 唯一的阶段状态计算出口，统一整理阶段状态、当前 Agent、摘要信息 |

第一版不强制新增 `LiveStatsDashboard.tsx`，避免一开始拆太散。

### `useAuditProgressViewModel.ts` 的职责边界

- 它是唯一的阶段状态计算出口
- [ProjectDetail.tsx](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail.tsx) 和 [AuditProgressDialog.tsx](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx) 只从它读取状态，不各自计算
- [auditEventStream.ts](file:///Users/harry/@dev/ccad/cad-review-frontend/src/pages/ProjectDetail/components/auditEventStream.ts) 只负责事件收发，不负责状态归纳
- 胶囊、弹窗、父页面使用同一份 view model，避免再次出现三处各算各的情况

---

## 七、建议实施顺序

1. 先抽出统一的阶段状态计算逻辑
   验收条件：
   `ProjectDetail.tsx` 里不再保留内联的阶段状态归纳逻辑，相关计算全部收进 `useAuditProgressViewModel.ts`。
   可用命令辅助检查：
   `rg -n "currentStep|agentName|phaseStatus" cad-review-frontend/src/pages/ProjectDetail.tsx`
2. 用新逻辑替换现在的 3 阶段卡片
3. 落 7 阶段流水线
4. 改日志面板为用户版时间轴
5. 增强最小化胶囊
6. 最后再补动画和可选统计卡

这个顺序的好处是，每一步都能单独看效果，不容易在一个大改动里迷路。

---

## 八、验证计划

### 手动验证
1. 启动前端开发服务器 `npm run dev`
2. 打开一个已准备好数据的项目，点击"开始审图"
3. 验证 7 个阶段会按真实事件依次变化
4. 验证默认日志视图是用户看得懂的时间轴
5. 验证开发者模式还能看到原始流式日志
6. 验证最小化 / 恢复行为
7. 验证中断按钮正常工作
8. 验证完成后能正确切到“查看审图报告”

### 重点验收项

- 前后端状态一致，不出现“顶部写一个阶段、流水线亮另一个阶段”
- 断流后轮询降级时，界面仍然能继续更新
- 胶囊和弹窗显示的当前 Agent 一致
- 没有因为展示升级影响原有中断流程
