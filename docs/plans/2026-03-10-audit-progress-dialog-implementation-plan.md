# 审图进度弹窗第一版 实现计划

> **给 Codex：** 必需子技能：使用 superpowers:executing-plans 来逐任务实现此计划。

**目标：** 实现审图进度弹窗第一版，补齐 7 阶段可视化、统一阶段状态计算、把日志改成用户看得懂的时间轴，并增强最小化胶囊。

**架构：** 保持现有 SSE / 轮询收发逻辑不变，在前端新增一层统一的 view model，把“当前阶段、节点状态、当前 Agent、摘要信息、胶囊文案”都收口到一个地方。弹窗、胶囊、父页面只读这份 view model，不再各自计算。另补一个很小的后端修正，避免上下文阶段的 ready 数展示错误。

**技术栈：** React 19、Vite、Vitest、Radix Dialog、lucide-react、Python pytest

---

## 实施约束

- 只做第一版，不实现复杂统计仪表盘和预计剩余时间
- 不改现有 SSE / 轮询协议
- 不随意重命名现有文件，`AuditEventList.tsx` 保留文件名，只调整内部表现
- 工作区已有未提交改动，严格避免碰无关文件

### 任务 1：修正上下文阶段 ready 数口径

**文件：**
- 修改：`cad-review-backend/services/audit_runtime/orchestrator.py`
- 测试：`cad-review-backend/tests/test_audit_runtime_events.py`

**步骤 1：编写失败的测试**

在 `cad-review-backend/tests/test_audit_runtime_events.py` 里补一个用 `ready_contexts` 返回值的场景，直接卡住当前错误口径：

```python
monkeypatch.setattr(
    orchestrator,
    "build_sheet_contexts",
    lambda project_id, db: {"ready_contexts": 2, "contexts_total": 2, "edges_total": 1},
)

...

assert "总控规划Agent 已整理好图纸上下文，当前有 2 张图纸可继续分析" in messages
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && pytest tests/test_audit_runtime_events.py -k plain_language_events -q
```

预期：FAIL，消息里仍然是 `0 张图纸` 或断言不匹配。

**步骤 3：编写最小实现**

在 `cad-review-backend/services/audit_runtime/orchestrator.py` 里把 ready 数读取改成优先读 `ready_contexts`，兼容旧字段：

```python
summary = context_summary or {}
ready_count = int(summary.get("ready_contexts", summary.get("ready", 0)))
```

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && pytest tests/test_audit_runtime_events.py -k plain_language_events -q
```

预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/tests/test_audit_runtime_events.py
git commit -m "fix: use ready_contexts for audit progress copy"
```

### 任务 2：新增统一的审图进度 view model

**文件：**
- 创建：`cad-review-frontend/src/pages/ProjectDetail/components/useAuditProgressViewModel.ts`
- 测试：`cad-review-frontend/src/pages/ProjectDetail/components/__tests__/useAuditProgressViewModel.test.ts`

**步骤 1：编写失败的测试**

先用纯函数测试把核心规则钉住，避免后面 UI 写着写着又分散计算：

```ts
import { buildAuditProgressViewModel } from '../useAuditProgressViewModel'

it('maps audit status and events into a single pipeline snapshot', () => {
  const viewModel = buildAuditProgressViewModel({
    progress: 35,
    startedAt: '2026-03-10T10:00:00',
    currentStep: '索引核对（5任务）',
    totalIssues: 3,
    providerLabel: 'Kimi SDK',
    events: [
      buildEvent({ id: 1, step_key: 'prepare', event_kind: 'phase_completed', progress_hint: 8 }),
      buildEvent({ id: 2, step_key: 'context', event_kind: 'phase_completed', progress_hint: 11 }),
      buildEvent({
        id: 3,
        step_key: 'relationship_discovery',
        event_kind: 'runner_broadcast',
        agent_name: '关系审查Agent',
        message: '关系审查Agent 正在复核第 15 组候选关系',
      }),
    ],
  })

  expect(viewModel.pipeline[0].state).toBe('complete')
  expect(viewModel.pipeline[1].state).toBe('complete')
  expect(viewModel.activeAgentName).toBe('关系审查Agent')
  expect(viewModel.summary.totalIssues).toBe(3)
})
```

再补一条测试，确认胶囊文案也来自同一份数据：

```ts
expect(viewModel.pill.label).toContain('关系审查Agent')
expect(viewModel.pill.label).toContain('35%')
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm run test -- src/pages/ProjectDetail/components/__tests__/useAuditProgressViewModel.test.ts
```

预期：FAIL，文件或导出不存在。

**步骤 3：编写最小实现**

在 `useAuditProgressViewModel.ts` 中先做纯数据层，不急着写 React 依赖：

```ts
export const PIPELINE_STEPS = [
  { stepKey: 'prepare', title: '数据准备' },
  { stepKey: 'context', title: '上下文构建' },
  { stepKey: 'relationship_discovery', title: '关系分析' },
  { stepKey: 'task_planning', title: '任务规划' },
  { stepKey: 'index', title: '索引核对' },
  { stepKey: 'dimension', title: '尺寸核对' },
  { stepKey: 'material', title: '材料核对' },
] as const

export function buildAuditProgressViewModel(input: BuildInput): AuditProgressViewModel {
  const activeEvent = pickActiveEvent(input.events)
  const pipeline = buildPipelineState(input.currentStep, input.events)
  return {
    pipeline,
    activeAgentName: activeEvent?.agent_name || '审图系统',
    activeMessage: activeEvent?.message || fallbackMessage(input.currentStep),
    summary: {
      progress: clampProgress(input.progress),
      totalIssues: input.totalIssues ?? 0,
      startedAt: input.startedAt ?? null,
      providerLabel: input.providerLabel ?? '',
    },
    pill: buildPill(activeEvent, input.progress, input.totalIssues),
  }
}
```

实现要求：

- `buildAuditProgressViewModel` 可单独测试
- hook 本体只负责 `useMemo`
- `runner_broadcast` 优先级高于普通 `phase_progress`
- 所有阶段状态都从这一个入口计算

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm run test -- src/pages/ProjectDetail/components/__tests__/useAuditProgressViewModel.test.ts
```

预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-frontend/src/pages/ProjectDetail/components/useAuditProgressViewModel.ts cad-review-frontend/src/pages/ProjectDetail/components/__tests__/useAuditProgressViewModel.test.ts
git commit -m "feat: add audit progress view model"
```

### 任务 3：让 ProjectDetail 只读 view model，不再内联算状态

**文件：**
- 修改：`cad-review-frontend/src/pages/ProjectDetail.tsx`
- 测试：`cad-review-frontend/src/pages/ProjectDetail/components/__tests__/ProjectDetail.auditState.test.ts`

**步骤 1：编写失败的测试**

补一条围绕“父页面不再自己算标题和阶段”的辅助测试，至少把 view model 接进来后的行为固定住：

```ts
import { buildAuditProgressViewModel } from '../useAuditProgressViewModel'

it('prefers shared progress view model output for active stage copy', () => {
  const viewModel = buildAuditProgressViewModel({
    progress: 18,
    currentStep: '规划审核任务图',
    totalIssues: 0,
    providerLabel: 'Kimi SDK',
    events: [],
  })

  expect(viewModel.pipeline.find((item) => item.stepKey === 'task_planning')?.state).toBe('current')
})
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm run test -- src/pages/ProjectDetail/components/__tests__/ProjectDetail.auditState.test.ts
```

预期：FAIL，相关辅助函数或调用方式尚未切换。

**步骤 3：编写最小实现**

在 `cad-review-frontend/src/pages/ProjectDetail.tsx` 中：

- 删除 `getStageTitle` / `getDialogPhases` 这类内联阶段归纳逻辑
- 用 `useAuditProgressViewModel` 统一产出弹窗、胶囊、摘要文案所需数据
- `AuditProgressDialog` 改成直接接收 `viewModel`

核心调用形态：

```ts
const auditProgressViewModel = useAuditProgressViewModel({
  auditStatus,
  events: auditEvents,
  providerLabel: getAuditProviderLabel(auditStatus?.provider_mode || auditProviderMode),
})

<AuditProgressDialog
  open
  viewModel={auditProgressViewModel}
  events={auditEvents}
  ...
/>
```

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm run test -- src/pages/ProjectDetail/components/__tests__/ProjectDetail.auditState.test.ts
cd /Users/harry/@dev/ccad && rg -n "getStageTitle|getDialogPhases" cad-review-frontend/src/pages/ProjectDetail.tsx
```

预期：

- Vitest PASS
- `rg` 没有输出

**步骤 5：提交**

```bash
git add cad-review-frontend/src/pages/ProjectDetail.tsx cad-review-frontend/src/pages/ProjectDetail/components/__tests__/ProjectDetail.auditState.test.ts
git commit -m "refactor: move audit progress state into shared view model"
```

### 任务 4：实现 7 阶段流水线和新弹窗布局

**文件：**
- 创建：`cad-review-frontend/src/pages/ProjectDetail/components/PipelineVisualization.tsx`
- 修改：`cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx`
- 测试：`cad-review-frontend/src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx`

**步骤 1：编写失败的测试**

先把新布局最关键的可见元素钉住：

```tsx
render(
  <AuditProgressDialog
    open
    viewModel={buildViewModel({
      progress: 48,
      activeAgentName: '尺寸审查Agent',
      totalIssues: 6,
      pipeline: [
        { stepKey: 'prepare', title: '数据准备', state: 'complete' },
        { stepKey: 'context', title: '上下文构建', state: 'complete' },
        { stepKey: 'dimension', title: '尺寸核对', state: 'current' },
      ],
    })}
    events={[]}
    onMinimize={() => {}}
    onRequestClose={async () => {}}
  />,
)

expect(screen.getByText('数据准备')).toBeInTheDocument()
expect(screen.getByText('上下文构建')).toBeInTheDocument()
expect(screen.getByText('尺寸核对')).toBeInTheDocument()
expect(screen.getByText(/已发现问题/)).toBeInTheDocument()
expect(screen.getByText(/尺寸审查Agent/)).toBeInTheDocument()
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm run test -- src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx
```

预期：FAIL，旧弹窗还没有新布局，也没有 `viewModel` 入参。

**步骤 3：编写最小实现**

在 `PipelineVisualization.tsx` 中先落静态可用版，不要先追复杂动效：

```tsx
export default function PipelineVisualization({ items }: { items: PipelineItem[] }) {
  return (
    <ol className="grid gap-3 md:grid-cols-2 xl:grid-cols-7">
      {items.map((item) => (
        <li key={item.stepKey} className={resolveStepClassName(item.state)}>
          <div className="text-xs text-muted-foreground">{item.indexLabel}</div>
          <div className="text-sm font-semibold">{item.title}</div>
          {item.issueCount !== null ? <div className="text-xs">发现 {item.issueCount} 处问题</div> : null}
        </li>
      ))}
    </ol>
  )
}
```

在 `AuditProgressDialog.tsx` 中：

- 顶部继续保留引擎、已运行时间、最小化、中断逻辑
- 中间换成“流水线 + 状态摘要区”
- 右侧继续挂 `AuditEventList`
- 保留现有关闭确认逻辑，不重写中断流程

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm run test -- src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx
```

预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-frontend/src/pages/ProjectDetail/components/PipelineVisualization.tsx cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx cad-review-frontend/src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx
git commit -m "feat: add pipeline audit progress dialog"
```

### 任务 5：把日志面板改成用户版时间轴，同时保留开发者模式

**文件：**
- 修改：`cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx`
- 测试：`cad-review-frontend/src/pages/ProjectDetail/components/__tests__/AuditEventList.test.tsx`

**步骤 1：编写失败的测试**

先加一条用户视角的测试，确保默认视图不是终端味：

```tsx
render(
  <AuditEventList
    events={[
      buildEvent({ id: 1, event_kind: 'phase_started', message: '总控规划Agent 正在整理图纸上下文' }),
      buildEvent({ id: 2, event_kind: 'runner_broadcast', message: '关系审查Agent 正在复核第 15 组候选关系' }),
    ]}
  />,
)

expect(screen.getByText('关键进展')).toBeInTheDocument()
expect(screen.getByText(/关系审查Agent 正在复核第 15 组候选关系/)).toBeInTheDocument()
expect(screen.queryByText('terminal://audit-stream')).not.toBeInTheDocument()
```

保留现有测试，继续保证：

- 默认不显示 `model_stream_delta`
- 开发者模式还能切去看原始流
- 心跳与重试仍会合并

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm run test -- src/pages/ProjectDetail/components/__tests__/AuditEventList.test.tsx
```

预期：FAIL，旧标题和旧布局仍存在。

**步骤 3：编写最小实现**

保留 `AuditEventList.tsx` 文件名，只换默认表现：

```tsx
const [viewMode, setViewMode] = useState<'summary' | 'process'>('summary')

return (
  <section className="border border-border bg-white">
    <header className="flex items-center justify-between px-4 py-3">
      <div>
        <h3 className="text-sm font-semibold">关键进展</h3>
        <p className="text-xs text-muted-foreground">这里只显示用户能看懂的进度播报</p>
      </div>
      <Button onClick={() => setViewMode(viewMode === 'summary' ? 'process' : 'summary')}>
        {viewMode === 'summary' ? '开发者模式' : '返回普通视图'}
      </Button>
    </header>
    {viewMode === 'summary' ? <TimelineFeed events={displayEvents} /> : <RawFeed events={rawEvents} />}
  </section>
)
```

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm run test -- src/pages/ProjectDetail/components/__tests__/AuditEventList.test.tsx
```

预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx cad-review-frontend/src/pages/ProjectDetail/components/__tests__/AuditEventList.test.tsx
git commit -m "feat: turn audit feed into user timeline"
```

### 任务 6：增强最小化胶囊并做一轮定向验证

**文件：**
- 修改：`cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx`
- 测试：`cad-review-frontend/src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx`

**步骤 1：编写失败的测试**

补一条胶囊文案测试，确认它不再只显示百分比：

```tsx
render(
  <AuditProgressPill
    progress={45}
    label="尺寸审查Agent 45%"
    issueCount={3}
    onClick={() => {}}
  />,
)

expect(screen.getByText('尺寸审查Agent 45%')).toBeInTheDocument()
expect(screen.getByText(/3 处问题/)).toBeInTheDocument()
```

**步骤 2：运行测试验证它失败**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm run test -- src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx
```

预期：FAIL，旧胶囊 props 还不支持这些内容。

**步骤 3：编写最小实现**

在 `AuditProgressDialog.tsx` 里把胶囊 props 改成显式传入，不再内部猜文案：

```tsx
export function AuditProgressPill({
  label,
  issueCount,
  progress,
  onClick,
}: {
  label: string
  issueCount: number
  progress: number
  onClick: () => void
}) {
  return (
    <button ...>
      <RefreshCw ... />
      <span>{label}</span>
      <span>{issueCount} 处问题</span>
      <span>{Math.round(progress)}%</span>
    </button>
  )
}
```

**步骤 4：运行测试验证它通过**

运行：

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm run test -- src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx
```

预期：PASS。

**步骤 5：提交**

```bash
git add cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx cad-review-frontend/src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx
git commit -m "feat: enrich minimized audit progress pill"
```

### 任务 7：最终验证

**文件：**
- 验证：`cad-review-backend/services/audit_runtime/orchestrator.py`
- 验证：`cad-review-frontend/src/pages/ProjectDetail.tsx`
- 验证：`cad-review-frontend/src/pages/ProjectDetail/components/AuditProgressDialog.tsx`
- 验证：`cad-review-frontend/src/pages/ProjectDetail/components/AuditEventList.tsx`
- 验证：`cad-review-frontend/src/pages/ProjectDetail/components/PipelineVisualization.tsx`
- 验证：`cad-review-frontend/src/pages/ProjectDetail/components/useAuditProgressViewModel.ts`

**步骤 1：运行后端定向测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-backend && pytest tests/test_audit_runtime_events.py -k plain_language_events -q
```

预期：PASS。

**步骤 2：运行前端定向测试**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm run test -- \
  src/pages/ProjectDetail/components/__tests__/useAuditProgressViewModel.test.ts \
  src/pages/ProjectDetail/components/__tests__/ProjectDetail.auditState.test.ts \
  src/pages/ProjectDetail/components/__tests__/AuditProgressDialog.test.tsx \
  src/pages/ProjectDetail/components/__tests__/AuditEventList.test.tsx \
  src/pages/ProjectDetail/components/__tests__/auditEventStream.test.ts
```

预期：PASS。

**步骤 3：运行前端定向 lint**

```bash
cd /Users/harry/@dev/ccad/cad-review-frontend && npm run lint -- \
  src/pages/ProjectDetail.tsx \
  src/pages/ProjectDetail/components/AuditProgressDialog.tsx \
  src/pages/ProjectDetail/components/AuditEventList.tsx \
  src/pages/ProjectDetail/components/PipelineVisualization.tsx \
  src/pages/ProjectDetail/components/useAuditProgressViewModel.ts
```

预期：PASS。

**步骤 4：人工检查**

- 开始审图后，7 个节点会按事件逐步变更
- 胶囊、弹窗、父页面显示的是同一当前 Agent
- 默认日志视图是用户能看懂的时间轴
- 开发者模式还能查看原始流式日志
- 最小化 / 恢复 / 中断流程保持可用

**步骤 5：提交**

```bash
git add cad-review-backend/services/audit_runtime/orchestrator.py cad-review-backend/tests/test_audit_runtime_events.py cad-review-frontend/src/pages/ProjectDetail.tsx cad-review-frontend/src/pages/ProjectDetail/components
git commit -m "feat: revamp audit progress dialog first version"
```
