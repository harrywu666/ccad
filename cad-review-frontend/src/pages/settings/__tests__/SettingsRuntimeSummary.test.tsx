import { render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import SettingsRuntimeSummary from '../SettingsRuntimeSummary';

vi.mock('@/api', () => ({
  getAuditRuntimeSummaries: vi.fn(),
}));

describe('SettingsRuntimeSummary', () => {
  it('renders finished audit runtime summaries for admin view', async () => {
    const api = await import('@/api');
    vi.mocked(api.getAuditRuntimeSummaries).mockResolvedValue({
      items: [
        {
          project_id: 'proj-1',
          project_name: 'test1',
          audit_version: 4,
          status: 'done',
          current_step: '生成报告',
          provider_mode: 'kimi_sdk',
          started_at: '2026-03-10T10:00:00',
          finished_at: '2026-03-10T10:05:30',
          duration_seconds: 330,
          counts: {
            agent_status_reported: 3,
            runner_help_requested: 2,
            runner_help_resolved: 2,
            output_validation_failed: 4,
            runner_observer_action: 1,
          },
          agent_summaries: [
            {
              agent_key: 'relationship_review_agent',
              agent_name: '关系审查Agent',
              report_count: 1,
              help_requested_count: 1,
              help_resolved_count: 1,
              output_unstable_count: 2,
            },
          ],
          recent_notes: [
            {
              event_kind: 'runner_help_resolved',
              message: 'Runner 已处理关系审查Agent 的求助请求',
              agent_name: 'Runner观察Agent',
              created_at: '2026-03-10T10:05:00',
            },
          ],
        },
      ],
    });

    render(<SettingsRuntimeSummary />);

    await waitFor(() => {
      expect(screen.getByText('test1 · v4')).toBeInTheDocument();
    });

    expect(screen.getByText('关系审查Agent')).toBeInTheDocument();
    expect(screen.getByText('Runner 已处理关系审查Agent 的求助请求')).toBeInTheDocument();
    expect(screen.getByText(/5 分 30 秒/)).toBeInTheDocument();
  });

  it('renders empty state when there are no finished summaries', async () => {
    const api = await import('@/api');
    vi.mocked(api.getAuditRuntimeSummaries).mockResolvedValue({ items: [] });

    render(<SettingsRuntimeSummary />);

    await waitFor(() => {
      expect(screen.getByText('最近还没有已结束审图的内部运行总结。')).toBeInTheDocument();
    });
  });
});
