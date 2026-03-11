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
        phases={[
          { title: '准备数据', description: '准备', state: 'complete' },
          { title: '深度审核', description: '审核', state: 'current' },
          { title: '生成报告', description: '报告', state: 'pending' },
        ]}
        pipeline={[
          { stepKey: 'prepare', title: '数据准备', description: '准备', state: 'complete', issueCount: 0 },
          { stepKey: 'context', title: '上下文构建', description: '上下文', state: 'complete', issueCount: 0 },
          { stepKey: 'dimension', title: '尺寸核对', description: '尺寸', state: 'current', issueCount: null },
        ]}
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
        phases={[
          { title: '准备数据', description: '准备', state: 'complete' },
          { title: '深度审核', description: '审核', state: 'current' },
          { title: '生成报告', description: '报告', state: 'pending' },
        ]}
        pipeline={[
          { stepKey: 'prepare', title: '数据准备', description: '准备', state: 'complete', issueCount: 0 },
          { stepKey: 'context', title: '上下文构建', description: '上下文', state: 'complete', issueCount: 0 },
          { stepKey: 'relationship_discovery', title: '关系分析', description: '关系', state: 'current', issueCount: null },
        ]}
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

    expect(screen.getByText('当前执行：关系审查Agent')).toBeInTheDocument();
    expect(screen.getAllByText(/正在复核第 15 组候选关系/).length).toBeGreaterThan(0);
    expect(screen.queryByText('{"raw":"provider fragment"}')).not.toBeInTheDocument();
  });

  it('renders the new pipeline and summary copy', () => {
    render(
      <AuditProgressDialog
        open
        progress={48}
        headline="尺寸比对核查"
        supportingText="当前阶段：尺寸核对（4任务）"
        startedAt="2026-03-10T10:00:00"
        phases={[
          { title: '准备数据', description: '准备', state: 'complete' },
          { title: '深度审核', description: '审核', state: 'current' },
          { title: '生成报告', description: '报告', state: 'pending' },
        ]}
        pipeline={[
          { stepKey: 'prepare', title: '数据准备', description: '准备', state: 'complete', issueCount: 0 },
          { stepKey: 'context', title: '上下文构建', description: '上下文', state: 'complete', issueCount: 0 },
          { stepKey: 'relationship_discovery', title: '关系分析', description: '关系', state: 'complete', issueCount: 0 },
          { stepKey: 'task_planning', title: '任务规划', description: '任务', state: 'complete', issueCount: 0 },
          { stepKey: 'index', title: '索引核对', description: '索引', state: 'complete', issueCount: 1 },
          { stepKey: 'dimension', title: '尺寸核对', description: '尺寸', state: 'current', issueCount: null },
          { stepKey: 'material', title: '材料核对', description: '材料', state: 'pending', issueCount: null },
        ]}
        activeAgentName="尺寸审查Agent"
        activeAgentMessage="尺寸审查Agent 正在比对第 4 组尺寸关系"
        totalIssues={6}
        events={[]}
        onMinimize={() => {}}
        onRequestClose={async () => {}}
      />,
    );

    expect(screen.getByText('审图流水线')).toBeInTheDocument();
    expect(screen.getByText('数据准备')).toBeInTheDocument();
    expect(screen.getByText('上下文构建')).toBeInTheDocument();
    expect(screen.getByText('尺寸核对')).toBeInTheDocument();
    expect(screen.getByText(/已发现问题 6/)).toBeInTheDocument();
    expect(screen.getAllByText(/当前 Agent：尺寸审查Agent/).length).toBeGreaterThan(0);
    expect(screen.queryByText('状态摘要')).not.toBeInTheDocument();
  });

  it('renders richer minimized pill copy', () => {
    render(
      <AuditProgressPill
        progress={45}
        onClick={() => {}}
      />,
    );

    expect(screen.getByText('审图中')).toBeInTheDocument();
    expect(screen.getByText('45%')).toBeInTheDocument();
  });

  it('formats elapsed text in mm:ss style when runtime is under one hour', () => {
    expect(
      formatAuditElapsedText('2026-03-10T10:00:00', new Date('2026-03-10T10:03:42')),
    ).toBe('已运行 03:42');
  });
});
