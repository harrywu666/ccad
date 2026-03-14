import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import SettingsPrompts from '../SettingsPrompts';

vi.mock('@/api', () => ({
  getAgentAssets: vi.fn(),
  updateAgentAssets: vi.fn(),
  getFeedbackAgentPromptAssets: vi.fn(),
  updateFeedbackAgentPromptAssets: vi.fn(),
}));

describe('SettingsPrompts', () => {
  it('renders review-kernel settings and feedback section', async () => {
    const api = await import('@/api');
    vi.mocked(api.getAgentAssets).mockResolvedValue({
      agent_id: 'review_kernel',
      title: '审图内核资产',
      items: [
        { key: 'soul_core', title: 'SOUL.md', description: 'core soul', file_name: 'SOUL.md', content: 'soul body' },
        { key: 'review_reporter_agent', title: 'AGENT_ReviewReporter.md', description: 'reporter', file_name: 'AGENT_ReviewReporter.md', content: 'reporter body' },
      ],
    });
    vi.mocked(api.getFeedbackAgentPromptAssets).mockResolvedValue({
      items: [
        { key: 'prompt', title: '误报反馈 Prompt', description: 'prompt desc', file_name: 'PROMPT.md', content: 'prompt body' },
        { key: 'agent', title: '误报反馈 AGENT.md', description: 'agent desc', file_name: 'AGENT.md', content: 'agent body' },
        { key: 'soul', title: '误报反馈 SOUL.md', description: 'soul desc', file_name: 'SOUL.md', content: 'soul body' },
      ],
    });

    render(<SettingsPrompts />);

    expect(await screen.findByText('审图内核资产')).toBeInTheDocument();
    expect(screen.getByText('误报反馈 Agent')).toBeInTheDocument();
    expect(screen.queryByText('副审 Worker Agent')).not.toBeInTheDocument();
    expect(screen.queryByText('旧版阶段设置（兼容层）')).not.toBeInTheDocument();
  });

  it('saves edited review-kernel asset', async () => {
    const api = await import('@/api');
    vi.mocked(api.getAgentAssets).mockResolvedValue({
      agent_id: 'review_kernel',
      title: '审图内核资产',
      items: [
        { key: 'review_reporter_agent', title: 'AGENT_ReviewReporter.md', description: 'reporter', file_name: 'AGENT_ReviewReporter.md', content: 'reporter body' },
      ],
    });
    vi.mocked(api.updateAgentAssets).mockResolvedValue({
      agent_id: 'review_kernel',
      title: '审图内核资产',
      items: [
        { key: 'review_reporter_agent', title: 'AGENT_ReviewReporter.md', description: 'reporter', file_name: 'AGENT_ReviewReporter.md', content: 'new reporter body' },
      ],
    });
    vi.mocked(api.getFeedbackAgentPromptAssets).mockResolvedValue({
      items: [
        { key: 'prompt', title: '误报反馈 Prompt', description: 'prompt desc', file_name: 'PROMPT.md', content: 'prompt body' },
        { key: 'agent', title: '误报反馈 AGENT.md', description: 'agent desc', file_name: 'AGENT.md', content: 'agent body' },
        { key: 'soul', title: '误报反馈 SOUL.md', description: 'soul desc', file_name: 'SOUL.md', content: 'soul body' },
      ],
    });

    render(<SettingsPrompts />);

    fireEvent.click(await screen.findByRole('button', { name: '编辑 AGENT_ReviewReporter.md' }));
    const textarea = await screen.findByDisplayValue('reporter body');
    fireEvent.change(textarea, { target: { value: 'new reporter body' } });
    fireEvent.click(screen.getByRole('button', { name: '保存' }));

    await waitFor(() => {
      expect(api.updateAgentAssets).toHaveBeenCalledWith('review_kernel', [
        { key: 'review_reporter_agent', content: 'new reporter body' },
      ]);
    });
    expect(await screen.findByText(/后面新的审图会直接用这版内容/)).toBeInTheDocument();
  });
});
