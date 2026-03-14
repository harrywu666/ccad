import { describe, expect, it } from 'vitest';
import {
  hasAuditReachedTerminalState,
  isAuditRunActiveStatus,
  resolveProjectDetailStep,
} from '../../../ProjectDetail';
import type { AuditStatus } from '@/types';

describe('ProjectDetail audit state helpers', () => {
  it('treats planning as an active audit status', () => {
    expect(isAuditRunActiveStatus('planning')).toBe(true);
    expect(isAuditRunActiveStatus('running')).toBe(true);
    expect(isAuditRunActiveStatus('idle')).toBe(false);
  });

  it('restores audit step from planning status even when project is still ready', () => {
    const status: AuditStatus = {
      project_id: 'proj-1',
      status: 'auditing',
      audit_version: 7,
      current_step: 'AI 分析图纸关系',
      progress: 14,
      total_issues: 0,
      run_status: 'planning',
      provider_mode: 'kimi_sdk',
      error: null,
      started_at: null,
      finished_at: null,
      scope_mode: null,
      scope_summary: null,
    };

    expect(resolveProjectDetailStep('ready', status)).toBe(2);
    expect(resolveProjectDetailStep('ready', null)).toBe(1);
  });

  it('recognizes done and failed audit states as terminal', () => {
    expect(hasAuditReachedTerminalState('done', 'auditing')).toBe(true);
    expect(hasAuditReachedTerminalState('running', 'failed')).toBe(true);
    expect(hasAuditReachedTerminalState('running', 'auditing')).toBe(false);
  });

  it('keeps audit step on runtime view while chief is doing final review or organizer work', () => {
    const finalReviewStatus: AuditStatus = {
      project_id: 'proj-1',
      status: 'auditing',
      audit_version: 7,
      current_step: '审图内核复核冲突结果',
      progress: 92,
      total_issues: 2,
      run_status: 'running',
      provider_mode: 'kimi_sdk',
      error: null,
      started_at: null,
      finished_at: null,
      scope_mode: null,
      scope_summary: null,
    };
    const organizerStatus: AuditStatus = {
      ...finalReviewStatus,
      current_step: '审图内核完成结果收束',
      progress: 98,
    };

    expect(resolveProjectDetailStep('ready', finalReviewStatus)).toBe(2);
    expect(resolveProjectDetailStep('ready', organizerStatus)).toBe(2);
  });
});
