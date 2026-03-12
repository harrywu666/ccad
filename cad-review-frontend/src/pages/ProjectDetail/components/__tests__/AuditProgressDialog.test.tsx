import { render, screen } from '@testing-library/react';
import { afterEach, beforeEach, vi } from 'vitest';
import AuditProgressDialog, { AuditProgressPill, formatAuditElapsedText } from '../AuditProgressDialog';
import type { AuditEvent } from '@/types/api';

const buildEvent = (overrides: Partial<AuditEvent> = {}): AuditEvent => ({
  id: 1,
  audit_version: 1,
  level: 'info',
  step_key: 'task_planning',
  agent_key: 'master_planner_agent',
  agent_name: '总控规划Agent',
  event_kind: 'phase_event',
  progress_hint: 18,
  message: '开始整理图纸',
  created_at: '2026-03-10T10:00:00',
  meta: {},
  ...overrides,
});

const baseChief = {
  currentAction: '主审 Agent 已派出 15 张副审任务卡',
  summary: '已形成 18 条怀疑卡，已派出 15 张副审任务卡，当前 2 张处理中。',
  bottleneck: '尺寸审查Agent 正在处理 图纸 A200，调用 标高一致性 Skill。',
  hypothesisCount: 18,
  plannedTaskCount: 15,
  runningTaskCount: 2,
  completedTaskCount: 6,
  queuedTaskCount: 7,
  blockedTaskCount: 0,
} as const;

const baseWorkerBoard = {
  running: [
    {
      key: 'sheet_semantic:A200',
      title: '图纸 A200',
      agentName: '尺寸审查Agent',
      skillLabel: '标高一致性 Skill',
      status: 'running' as const,
      statusLabel: '处理中',
      summary: '图纸 A200 正在抽取单图尺寸语义。',
      updatedAt: '2026-03-10T10:03:42',
    },
  ],
  completed: [
    {
      key: 'sheet_semantic:A101',
      title: '图纸 A101',
      agentName: '尺寸审查Agent',
      skillLabel: '标高一致性 Skill',
      status: 'completed' as const,
      statusLabel: '已收束',
      summary: '图纸 A101 已收束本轮输出，等待主审消化结果。',
      updatedAt: '2026-03-10T10:02:12',
    },
  ],
  blocked: [],
  queuedCount: 7,
};

const baseLedger = {
  issueCount: 2,
  runningTaskCount: 2,
  completedTaskCount: 6,
  queuedTaskCount: 7,
  blockedTaskCount: 0,
} as const;

describe('AuditProgressDialog', () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it('shows elapsed run time instead of eta text', () => {
    vi.setSystemTime(new Date('2026-03-10T10:03:42'));

    render(
      <AuditProgressDialog
        open
        progress={48}
        headline="尺寸比对核查"
        supportingText="系统正在持续审图"
        startedAt="2026-03-10T10:00:00"
        pipeline={[
          { stepKey: 'chief_prepare', title: '主审准备', description: '准备', state: 'complete', issueCount: 0 },
          { stepKey: 'worker_execution', title: '副审执行', description: '执行', state: 'current', issueCount: null },
          { stepKey: 'chief_finalize', title: '主审收束', description: '收束', state: 'pending', issueCount: null },
        ]}
        chief={baseChief}
        workerBoard={baseWorkerBoard}
        resultLedger={baseLedger}
        activeAgentName="尺寸审查Agent"
        activeAgentMessage="尺寸审查Agent 正在比对第 4 组尺寸关系"
        totalIssues={2}
        events={[]}
        onMinimize={() => {}}
        onRequestClose={async () => {}}
      />,
    );

    expect(screen.getByText('已运行 03:42')).toBeInTheDocument();
    expect(screen.queryByText(/预计/)).not.toBeInTheDocument();
  });

  it('prefers runner broadcast in the central status copy', () => {
    render(
      <AuditProgressDialog
        open
        progress={35}
        headline="索引断链核对"
        supportingText="系统正在持续审图"
        startedAt="2026-03-10T10:00:00"
        pipeline={[
          { stepKey: 'chief_prepare', title: '主审准备', description: '准备', state: 'complete', issueCount: 0 },
          { stepKey: 'worker_execution', title: '副审执行', description: '执行', state: 'current', issueCount: null },
          { stepKey: 'chief_finalize', title: '主审收束', description: '收束', state: 'pending', issueCount: null },
        ]}
        chief={baseChief}
        workerBoard={baseWorkerBoard}
        resultLedger={baseLedger}
        events={[
          buildEvent({
            id: 2,
            message: '{"raw":"provider fragment"}',
            event_kind: 'provider_stream_delta',
          }),
          buildEvent({
            id: 3,
            event_kind: 'runner_broadcast',
            agent_name: '关系审查Agent',
            message: '关系审查Agent 正在复核第 15 组候选关系，当前核对 A-15 和 A-16',
            meta: { stream_layer: 'user_facing' },
          }),
        ]}
        onMinimize={() => {}}
        onRequestClose={async () => {}}
      />,
    );

    expect(screen.getByText((content) => content.includes('当前焦点：') && content.includes('关系审查Agent'))).toBeInTheDocument();
    expect(screen.getAllByText(/正在复核第 15 组候选关系/).length).toBeGreaterThan(0);
    expect(screen.queryByText('{"raw":"provider fragment"}')).not.toBeInTheDocument();
  });

  it('renders the new command center layout', () => {
    render(
      <AuditProgressDialog
        open
        progress={48}
        headline="尺寸比对核查"
        supportingText="当前阶段：尺寸核对（4任务）"
        startedAt="2026-03-10T10:00:00"
        pipeline={[
          { stepKey: 'chief_prepare', title: '主审准备', description: '准备', state: 'complete', issueCount: 0 },
          { stepKey: 'worker_execution', title: '副审执行', description: '执行', state: 'current', issueCount: 1 },
          { stepKey: 'chief_finalize', title: '主审收束', description: '收束', state: 'pending', issueCount: null },
        ]}
        chief={baseChief}
        workerBoard={baseWorkerBoard}
        resultLedger={baseLedger}
        activeAgentName="尺寸审查Agent"
        activeAgentMessage="尺寸审查Agent 正在比对第 4 组尺寸关系"
        totalIssues={6}
        events={[]}
        onMinimize={() => {}}
        onRequestClose={async () => {}}
      />,
    );

    expect(screen.getByText('主审正在组织副审审图')).toBeInTheDocument();
    expect(screen.getByText('主审指挥台')).toBeInTheDocument();
    expect(screen.getByText('副审任务墙')).toBeInTheDocument();
    expect(screen.queryByText('尺寸核对')).not.toBeInTheDocument();
    expect(screen.getByText('图纸 A200')).toBeInTheDocument();
    expect(screen.getAllByText('标高一致性 Skill').length).toBeGreaterThan(0);
    expect(screen.getByText('结果台账')).toBeInTheDocument();
    expect(screen.getByText('全局阶段带')).toBeInTheDocument();
  });

  it('renders richer minimized pill copy', () => {
    render(
      <AuditProgressPill
        progress={45}
        onClick={() => {}}
      />,
    );

    expect(screen.getByText('主审调度中')).toBeInTheDocument();
    expect(screen.getByText('45%')).toBeInTheDocument();
  });

  it('formats elapsed text in mm:ss style when runtime is under one hour', () => {
    expect(
      formatAuditElapsedText('2026-03-10T10:00:00', new Date('2026-03-10T10:03:42')),
    ).toBe('已运行 03:42');
  });
});
