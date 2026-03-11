import { describe, expect, it } from 'vitest';
import type { AuditStatus } from '@/types';
import type { AuditEvent } from '@/types/api';
import { buildAuditProgressViewModel } from '../useAuditProgressViewModel';

const buildEvent = (overrides: Partial<AuditEvent> = {}): AuditEvent => ({
  id: 1,
  audit_version: 1,
  level: 'info',
  step_key: 'task_planning',
  agent_key: 'master_planner_agent',
  agent_name: '总控规划Agent',
  event_kind: 'phase_progress',
  progress_hint: 18,
  message: '总控规划Agent 正在生成审核任务图',
  created_at: '2026-03-10T10:00:00',
  meta: {},
  ...overrides,
});

const buildStatus = (overrides: Partial<AuditStatus> = {}): AuditStatus => ({
  project_id: 'proj-1',
  status: 'auditing',
  audit_version: 7,
  current_step: '索引核对（5任务）',
  progress: 35,
  total_issues: 3,
  run_status: 'running',
  provider_mode: 'kimi_sdk',
  error: null,
  started_at: '2026-03-10T10:00:00',
  finished_at: null,
  scope_mode: null,
  scope_summary: null,
  ...overrides,
});

describe('buildAuditProgressViewModel', () => {
  it('maps audit status and events into a single pipeline snapshot', () => {
    const viewModel = buildAuditProgressViewModel({
      auditStatus: buildStatus(),
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
    });

    expect(viewModel.pipeline[0].state).toBe('complete');
    expect(viewModel.pipeline[1].state).toBe('complete');
    expect(viewModel.pipeline.find((item) => item.stepKey === 'relationship_discovery')?.state).toBe('complete');
    expect(viewModel.pipeline.find((item) => item.stepKey === 'index')?.state).toBe('current');
    expect(viewModel.activeAgentName).toBe('关系审查Agent');
    expect(viewModel.activeAgentMessage).toContain('第 15 组候选关系');
    expect(viewModel.totalIssues).toBe(3);
  });

  it('builds pill copy from the same shared state', () => {
    const viewModel = buildAuditProgressViewModel({
      auditStatus: buildStatus({ progress: 45, total_issues: 6 }),
      providerLabel: 'Kimi SDK',
      events: [
        buildEvent({
          id: 9,
          step_key: 'dimension',
          event_kind: 'runner_broadcast',
          agent_name: '尺寸审查Agent',
          message: '尺寸审查Agent 正在比对第 4 组尺寸关系',
        }),
      ],
    });

    expect(viewModel.pill.label).toContain('尺寸审查Agent');
    expect(viewModel.pill.label).toContain('45%');
    expect(viewModel.pill.issueCount).toBe(6);
  });

  it('falls back to audit status copy when no runner broadcast exists', () => {
    const viewModel = buildAuditProgressViewModel({
      auditStatus: buildStatus({
        current_step: '规划审核任务图',
        progress: 18,
        total_issues: 0,
      }),
      providerLabel: 'Kimi SDK',
      events: [],
    });

    expect(viewModel.headline).toBe('预规划审核任务');
    expect(viewModel.supportingText).toBe('当前阶段：规划审核任务图');
    expect(viewModel.pipeline.find((item) => item.stepKey === 'task_planning')?.state).toBe('current');
  });

  it('marks earlier stages complete when current stage has moved forward', () => {
    const viewModel = buildAuditProgressViewModel({
      auditStatus: buildStatus({
        current_step: '尺寸核对（22项检查）',
        progress: 49,
      }),
      providerLabel: 'Kimi SDK',
      events: [
        buildEvent({
          id: 20,
          step_key: 'index',
          event_kind: 'phase_completed',
          progress_hint: 45,
          message: '索引审查Agent 已完成 AI 复核',
        }),
      ],
    });

    expect(viewModel.pipeline.find((item) => item.stepKey === 'prepare')?.state).toBe('complete');
    expect(viewModel.pipeline.find((item) => item.stepKey === 'context')?.state).toBe('complete');
    expect(viewModel.pipeline.find((item) => item.stepKey === 'relationship_discovery')?.state).toBe('complete');
    expect(viewModel.pipeline.find((item) => item.stepKey === 'dimension')?.state).toBe('current');
  });
});
