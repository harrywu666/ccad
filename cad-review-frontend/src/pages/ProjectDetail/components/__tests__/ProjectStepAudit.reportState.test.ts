import { describe, expect, it } from 'vitest';
import {
  buildIssuePreviewSignature,
  isAuditReportRunning,
  resolveAuditReportPresentation,
} from '../project-detail/ProjectStepAudit';
import type { AuditStatus } from '@/types';
import type { AuditHistoryItem } from '@/types/api';

describe('ProjectStepAudit report presentation', () => {
  it('shows interrupted copy when selected audit version failed', () => {
    const auditStatus: AuditStatus = {
      project_id: 'proj-1',
      status: 'done',
      audit_version: 1,
      current_step: '执行失败',
      progress: 52,
      total_issues: 12,
      run_status: 'failed',
      provider_mode: 'kimi_sdk',
      error: '',
      started_at: '2026-03-10T21:40:08.722007',
      finished_at: '2026-03-10T22:14:37.595677',
      scope_mode: 'full',
      scope_summary: '{"total":44,"ready":44}',
    };
    const versionMeta: AuditHistoryItem = {
      version: 1,
      status: 'failed',
      current_step: '执行失败',
      progress: 52,
      count: 12,
      grouped_count: 7,
      types: { index: 12 },
      error: '',
      started_at: '2026-03-10T21:40:08.722007',
      finished_at: '2026-03-10T22:14:37.595677',
      scope_mode: 'full',
    };

    expect(resolveAuditReportPresentation(auditStatus, versionMeta)).toEqual({
      tone: 'error',
      title: '审核已中断',
      description: '这轮审图没有正常跑完，当前展示的是中断前已经写入的问题，不是完整报告。开发层运行细节可以去设置页里的运行总结查看。',
    });
  });

  it('treats planning and running as report-running states', () => {
    const status: AuditStatus = {
      project_id: 'proj-1',
      status: 'auditing',
      audit_version: 2,
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
    expect(isAuditReportRunning('ready', status)).toBe(true);
    expect(isAuditReportRunning('done', { ...status, status: 'done', run_status: 'done' })).toBe(false);
  });

  it('changes preview signature when evidence_json changes', () => {
    const base = {
      id: 'group_1',
      description: '问题描述',
      location: '索引A1',
      finding_status: 'needs_review',
      review_round: 1,
      confidence: 0.5,
      evidence_json: '{"anchors":[]}',
      issue_ids: ['i1'],
    };
    const first = buildIssuePreviewSignature(base as any);
    const second = buildIssuePreviewSignature({
      ...base,
      evidence_json: '{"anchors":[{"x":1}]}',
    } as any);

    expect(first).not.toBe(second);
  });

  it('keeps running copy when selected version itself is still running', () => {
    const staleStatus: AuditStatus = {
      project_id: 'proj-1',
      status: 'done',
      audit_version: 1,
      current_step: '旧任务已完成',
      progress: 100,
      total_issues: 9,
      run_status: 'done',
      provider_mode: 'kimi_sdk',
      error: null,
      started_at: null,
      finished_at: null,
      scope_mode: 'full',
      scope_summary: null,
    };
    const runningVersion: AuditHistoryItem = {
      version: 2,
      status: 'running',
      current_step: '关系审查',
      progress: 12,
      count: 0,
      grouped_count: 0,
      types: { index: 0, dimension: 0, material: 0 },
      error: null,
      started_at: null,
      finished_at: null,
      scope_mode: 'full',
    };

    expect(resolveAuditReportPresentation(staleStatus, runningVersion)).toEqual({
      tone: 'warning',
      title: '审图进行中',
      description: '审图还在持续处理中，问题会陆续追加到下方列表。你可以先处理已经出现的问题。',
    });
  });
});
