import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import SettingsReviewWorkerSkills from '../SettingsReviewWorkerSkills';

vi.mock('@/api', () => ({
  getReviewWorkerSkillAssets: vi.fn(),
  updateReviewWorkerSkillAssets: vi.fn(),
}));

describe('SettingsReviewWorkerSkills', () => {
  it('renders editable worker skill files', async () => {
    const api = await import('@/api');
    vi.mocked(api.getReviewWorkerSkillAssets).mockResolvedValue({
      items: [
        { key: 'index_reference', title: '索引引用 Skill', description: 'index desc', file_name: 'SKILL.md', content: 'index body' },
        { key: 'material_semantic_consistency', title: '材料语义一致性 Skill', description: 'material desc', file_name: 'SKILL.md', content: 'material body' },
      ],
    });

    render(<SettingsReviewWorkerSkills />);

    expect(await screen.findByText('Worker Skills')).toBeInTheDocument();
    expect(screen.getByDisplayValue('index body')).toBeInTheDocument();
    expect(screen.getByDisplayValue('material body')).toBeInTheDocument();
  });

  it('saves edited worker skill content', async () => {
    const api = await import('@/api');
    vi.mocked(api.getReviewWorkerSkillAssets).mockResolvedValue({
      items: [
        { key: 'index_reference', title: '索引引用 Skill', description: 'index desc', file_name: 'SKILL.md', content: 'index body' },
      ],
    });
    vi.mocked(api.updateReviewWorkerSkillAssets).mockResolvedValue({
      items: [
        { key: 'index_reference', title: '索引引用 Skill', description: 'index desc', file_name: 'SKILL.md', content: 'new index body' },
      ],
    });

    render(<SettingsReviewWorkerSkills />);

    const textarea = await screen.findByDisplayValue('index body');
    fireEvent.change(textarea, { target: { value: 'new index body' } });
    fireEvent.click(screen.getByRole('button', { name: '保存全部' }));

    await waitFor(() => {
      expect(api.updateReviewWorkerSkillAssets).toHaveBeenCalledWith([
        { key: 'index_reference', content: 'new index body' },
      ]);
    });
    expect(await screen.findByText(/skills 已保存/)).toBeInTheDocument();
  });
});
