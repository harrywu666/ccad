import { fireEvent, render, screen } from '@testing-library/react';
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
  title: '主审',
  currentAction: '主审 Agent 已派出 15 张副审任务卡',
  summary: '已形成 18 条怀疑卡，已派出 15 张副审任务卡，当前 2 张处理中。',
  assignedTaskCount: 15,
  activeWorkerCount: 2,
  completedWorkerCount: 6,
  blockedWorkerCount: 1,
  queuedTaskCount: 7,
  issueCount: 2,
  updatedAt: '2026-03-10T10:03:00',
} as const;

const baseWorkerWall = {
  active: [
    {
      key: 'worker_skill:elevation_consistency:A200:SELF',
      workerName: '标高副审',
      skillId: 'elevation_consistency',
      skillLabel: '标高一致性 Skill',
      taskTitle: '图纸 A200',
      currentAction: '正在抽取单图标高语义',
      status: 'active' as const,
      statusLabel: '进行中',
      updatedAt: '2026-03-10T10:03:42',
      context: { sheet_no: 'A200' },
      recentActions: [
        { at: '2026-03-10T10:03:02', label: '调用 Skill', text: '已启动本轮技能执行' },
        { at: '2026-03-10T10:03:42', label: '现场播报', text: '正在抽取单图标高语义' },
      ],
    },
  ],
  recentCompleted: [
    {
      key: 'worker_skill:index_reference:A101:A402',
      workerName: '索引副审',
      skillId: 'index_reference',
      skillLabel: '索引引用 Skill',
      taskTitle: 'A101 ↔ A402',
      currentAction: '已收束并保存输出',
      status: 'completed' as const,
      statusLabel: '已完成',
      updatedAt: '2026-03-10T10:02:12',
      context: { source_sheet_no: 'A101', target_sheet_no: 'A402' },
      recentActions: [
        { at: '2026-03-10T10:02:12', label: '保存输出', text: '已收束并保存输出' },
      ],
    },
  ],
};

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
        headline="主审派工"
        supportingText="系统正在持续审图"
        startedAt="2026-03-10T10:00:00"
        chief={baseChief}
        workerWall={baseWorkerWall}
        debugTimeline={{ enabled: false, events: [] }}
        onMinimize={() => {}}
        onRequestClose={async () => {}}
      />,
    );

    expect(screen.getByText('已运行 03:42')).toBeInTheDocument();
    expect(screen.queryByText(/预计/)).not.toBeInTheDocument();
  });

  it('renders chief card, worker wall, and hides removed primary sections', () => {
    render(
      <AuditProgressDialog
        open
        progress={48}
        headline="主审派工"
        supportingText="当前阶段：主审派发副审任务"
        startedAt="2026-03-10T10:00:00"
        chief={baseChief}
        workerWall={baseWorkerWall}
        debugTimeline={{ enabled: false, events: [] }}
        onMinimize={() => {}}
        onRequestClose={async () => {}}
      />,
    );

    expect(screen.getByText('主审 + 副审实时现场')).toBeInTheDocument();
    expect(screen.getByText('主审总控卡')).toBeInTheDocument();
    expect(screen.getByText('副审实时卡墙')).toBeInTheDocument();
    expect(screen.getAllByText('最近完成').length).toBeGreaterThan(0);
    expect(screen.getByText('标高副审')).toBeInTheDocument();
    expect(screen.getAllByText('正在抽取单图标高语义').length).toBeGreaterThan(0);
    expect(screen.queryByText('结果台账')).not.toBeInTheDocument();
    expect(screen.queryByText('全局阶段带')).not.toBeInTheDocument();
  });

  it('opens filtered worker detail drawer from a worker card', () => {
    render(
      <AuditProgressDialog
        open
        progress={48}
        headline="主审派工"
        supportingText="当前阶段：主审派发副审任务"
        startedAt="2026-03-10T10:00:00"
        chief={baseChief}
        workerWall={baseWorkerWall}
        debugTimeline={{
          enabled: true,
          events: [
            buildEvent({
              id: 2,
              event_kind: 'runner_broadcast',
              agent_name: '尺寸审查Agent',
              message: '尺寸审查Agent 正在抽取 A200 的单图标高语义',
              meta: {
                session_key: 'worker_skill:elevation_consistency:A200:SELF',
              },
            }),
            buildEvent({
              id: 3,
              event_kind: 'runner_broadcast',
              agent_name: '索引审查Agent',
              message: '索引审查Agent 正在核对 A101 和 A402',
              meta: {
                session_key: 'worker_skill:index_reference:A101:A402',
              },
            }),
          ],
        }}
        onMinimize={() => {}}
        onRequestClose={async () => {}}
      />,
    );

    fireEvent.click(screen.getAllByRole('button', { name: '查看详情' })[0]!);

    expect(screen.getByText('按会话 worker_skill:elevation_consistency:A200:SELF 过滤的原始事件。')).toBeInTheDocument();
    expect(screen.getAllByText(/抽取 A200 的单图标高语义/).length).toBeGreaterThan(0);
    expect(screen.queryByText(/核对 A101 和 A402/)).not.toBeInTheDocument();
  });

  it('keeps full debug timeline behind a secondary trigger', () => {
    render(
      <AuditProgressDialog
        open
        progress={35}
        headline="主审派工"
        supportingText="系统正在持续审图"
        startedAt="2026-03-10T10:00:00"
        chief={baseChief}
        workerWall={baseWorkerWall}
        debugTimeline={{
          enabled: true,
          events: [
            buildEvent({
              id: 3,
              event_kind: 'runner_broadcast',
              agent_name: '关系审查Agent',
              message: '关系审查Agent 正在复核第 15 组候选关系',
              meta: { stream_layer: 'user_facing' },
            }),
          ],
        }}
        onMinimize={() => {}}
        onRequestClose={async () => {}}
      />,
    );

    expect(screen.queryByText('全部动作流')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: /全部动作/ }));
    expect(screen.getByText('全部动作流')).toBeInTheDocument();
    expect(screen.getAllByText(/复核第 15 组候选关系/).length).toBeGreaterThan(0);
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
