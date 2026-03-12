import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import SettingsFeedbackAgentPrompts from '../SettingsFeedbackAgentPrompts';

vi.mock('@/api', () => ({
  getFeedbackAgentPromptAssets: vi.fn(),
  updateFeedbackAgentPromptAssets: vi.fn(),
}));

describe('SettingsFeedbackAgentPrompts', () => {
  it('renders three editable feedback agent assets', async () => {
    const api = await import('@/api');
    vi.mocked(api.getFeedbackAgentPromptAssets).mockResolvedValue({
      items: [
        { key: 'prompt', title: '误报反馈 PROMPT.md', description: 'prompt desc', file_name: 'PROMPT.md', content: 'prompt body' },
        { key: 'agent', title: '误报反馈 AGENT.md', description: 'agent desc', file_name: 'AGENT.md', content: 'agent body' },
        { key: 'soul', title: '误报反馈 SOUL.md', description: 'soul desc', file_name: 'SOUL.md', content: 'soul body' },
      ],
    });

    render(<SettingsFeedbackAgentPrompts />);

    expect(await screen.findByText('误报反馈 Agent')).toBeInTheDocument();
    expect(screen.getByDisplayValue('prompt body')).toBeInTheDocument();
    expect(screen.getByDisplayValue('agent body')).toBeInTheDocument();
    expect(screen.getByDisplayValue('soul body')).toBeInTheDocument();
  });

  it('saves edited asset content', async () => {
    const api = await import('@/api');
    vi.mocked(api.getFeedbackAgentPromptAssets).mockResolvedValue({
      items: [
        { key: 'prompt', title: '误报反馈 PROMPT.md', description: 'prompt desc', file_name: 'PROMPT.md', content: 'prompt body' },
        { key: 'agent', title: '误报反馈 AGENT.md', description: 'agent desc', file_name: 'AGENT.md', content: 'agent body' },
        { key: 'soul', title: '误报反馈 SOUL.md', description: 'soul desc', file_name: 'SOUL.md', content: 'soul body' },
      ],
    });
    vi.mocked(api.updateFeedbackAgentPromptAssets).mockResolvedValue({
      items: [
        { key: 'prompt', title: '误报反馈 PROMPT.md', description: 'prompt desc', file_name: 'PROMPT.md', content: 'new prompt body' },
        { key: 'agent', title: '误报反馈 AGENT.md', description: 'agent desc', file_name: 'AGENT.md', content: 'agent body' },
        { key: 'soul', title: '误报反馈 SOUL.md', description: 'soul desc', file_name: 'SOUL.md', content: 'soul body' },
      ],
    });

    render(<SettingsFeedbackAgentPrompts />);

    const textareas = await screen.findAllByRole('textbox');
    fireEvent.change(textareas[0], { target: { value: 'new prompt body' } });
    fireEvent.click(screen.getByRole('button', { name: '保存全部' }));

    await waitFor(() => {
      expect(api.updateFeedbackAgentPromptAssets).toHaveBeenCalledWith([
        { key: 'prompt', content: 'new prompt body' },
      ]);
    });
    expect(await screen.findByText(/文件已保存/)).toBeInTheDocument();
  });
});
