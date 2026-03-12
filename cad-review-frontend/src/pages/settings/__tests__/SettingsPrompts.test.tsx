import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import SettingsPrompts from '../SettingsPrompts';

vi.mock('@/api', () => ({
  getAgentAssets: vi.fn(),
  updateAgentAssets: vi.fn(),
  getReviewWorkerSkillAssets: vi.fn(),
  updateReviewWorkerSkillAssets: vi.fn(),
  getFeedbackAgentPromptAssets: vi.fn(),
  updateFeedbackAgentPromptAssets: vi.fn(),
  getAIPromptSettings: vi.fn(),
  updateAIPromptSettings: vi.fn(),
  resetAIPromptStage: vi.fn(),
}));

describe('SettingsPrompts', () => {
  it('renders agent-first settings with worker skills and legacy section', async () => {
    const api = await import('@/api');
    vi.mocked(api.getAgentAssets).mockImplementation(async agentId => ({
      agent_id: agentId,
      title: agentId,
      items: [
        { key: 'agent', title: `${agentId} AGENTS.md`, description: 'agent desc', file_name: 'AGENTS.md', content: `${agentId} agent body` },
        { key: 'soul', title: `${agentId} SOUL.md`, description: 'soul desc', file_name: 'SOUL.md', content: `${agentId} soul body` },
        { key: 'memory', title: `${agentId} MEMORY.md`, description: 'memory desc', file_name: 'MEMORY.md', content: `${agentId} memory body` },
      ],
    }));
    vi.mocked(api.getReviewWorkerSkillAssets).mockResolvedValue({
      items: [
        { key: 'index_reference', title: '索引引用 Skill', description: 'index desc', file_name: 'SKILL.md', content: 'index skill body' },
        { key: 'material_semantic_consistency', title: '材料语义一致性 Skill', description: 'material desc', file_name: 'SKILL.md', content: 'material skill body' },
      ],
    });
    vi.mocked(api.getFeedbackAgentPromptAssets).mockResolvedValue({
      items: [
        { key: 'prompt', title: '误报反馈 Prompt', description: 'prompt desc', file_name: 'PROMPT.md', content: 'prompt body' },
        { key: 'agent', title: '误报反馈 AGENT.md', description: 'agent desc', file_name: 'AGENT.md', content: 'agent body' },
        { key: 'soul', title: '误报反馈 SOUL.md', description: 'soul desc', file_name: 'SOUL.md', content: 'soul body' },
      ],
    });
    vi.mocked(api.getAIPromptSettings).mockResolvedValue({
      stages: [],
    });

    render(<SettingsPrompts />);

    expect(await screen.findByText('主审 Agent')).toBeInTheDocument();
    expect(screen.getByText('副审 Worker Agent')).toBeInTheDocument();
    expect(screen.getByText('运行守护 Agent')).toBeInTheDocument();
    expect(await screen.findByText('Worker Skills')).toBeInTheDocument();
    expect(screen.getByText('误报反馈 Agent')).toBeInTheDocument();
    expect(screen.getByText('旧版阶段设置（兼容层）')).toBeInTheDocument();
  });

  it('saves edited chief review agent asset', async () => {
    const api = await import('@/api');
    vi.mocked(api.getAgentAssets).mockImplementation(async agentId => ({
      agent_id: agentId,
      title: agentId,
      items: [
        { key: 'agent', title: `${agentId} AGENTS.md`, description: 'agent desc', file_name: 'AGENTS.md', content: `${agentId} agent body` },
        { key: 'soul', title: `${agentId} SOUL.md`, description: 'soul desc', file_name: 'SOUL.md', content: `${agentId} soul body` },
        { key: 'memory', title: `${agentId} MEMORY.md`, description: 'memory desc', file_name: 'MEMORY.md', content: `${agentId} memory body` },
      ],
    }));
    vi.mocked(api.updateAgentAssets).mockResolvedValue({
      agent_id: 'chief_review',
      title: 'chief_review',
      items: [
        { key: 'agent', title: 'chief_review AGENTS.md', description: 'agent desc', file_name: 'AGENTS.md', content: 'new chief agent body' },
        { key: 'soul', title: 'chief_review SOUL.md', description: 'soul desc', file_name: 'SOUL.md', content: 'chief_review soul body' },
        { key: 'memory', title: 'chief_review MEMORY.md', description: 'memory desc', file_name: 'MEMORY.md', content: 'chief_review memory body' },
      ],
    });
    vi.mocked(api.getReviewWorkerSkillAssets).mockResolvedValue({ items: [] });
    vi.mocked(api.getFeedbackAgentPromptAssets).mockResolvedValue({
      items: [
        { key: 'prompt', title: '误报反馈 Prompt', description: 'prompt desc', file_name: 'PROMPT.md', content: 'prompt body' },
        { key: 'agent', title: '误报反馈 AGENT.md', description: 'agent desc', file_name: 'AGENT.md', content: 'agent body' },
        { key: 'soul', title: '误报反馈 SOUL.md', description: 'soul desc', file_name: 'SOUL.md', content: 'soul body' },
      ],
    });
    vi.mocked(api.getAIPromptSettings).mockResolvedValue({ stages: [] });

    render(<SettingsPrompts />);

    const chiefAgentTextarea = await screen.findByDisplayValue('chief_review agent body');
    fireEvent.change(chiefAgentTextarea, { target: { value: 'new chief agent body' } });
    const saveButtons = screen.getAllByRole('button', { name: '保存' });
    fireEvent.click(saveButtons[0]);

    await waitFor(() => {
      expect(api.updateAgentAssets).toHaveBeenCalledWith('chief_review', [
        { key: 'agent', content: 'new chief agent body' },
      ]);
    });
    expect(await screen.findByText(/后面新的 Agent 运行会直接用这版内容/)).toBeInTheDocument();
  });
});
