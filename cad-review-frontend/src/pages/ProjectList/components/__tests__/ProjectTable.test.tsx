import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import ProjectTable from '../ProjectTable';
import type { Category, Project } from '@/types';

const categories: Category[] = [
  { id: 'commercial', name: '商业', color: '#000000', sort_order: 1 },
];

const statusMap = {
  new: { label: '待开始', variant: 'secondary' as const },
  catalog_locked: { label: '目录已确认', variant: 'warning' as const },
  matching: { label: '匹配中', variant: 'warning' as const },
  ready: { label: '待审核', variant: 'warning' as const },
  auditing: { label: '审核中', variant: 'warning' as const },
  done: { label: '已完成', variant: 'success' as const },
};

const buildProject = (overrides: Partial<Project> = {}): Project => ({
  id: 'proj_1',
  name: 'test1',
  category: 'commercial',
  tags: null,
  description: null,
  cache_version: 1,
  created_at: '2026-03-09T10:00:00',
  status: 'auditing',
  updated_at: '2026-03-11T10:00:00',
  current_step: 'AI 分析图纸关系（12任务）',
  progress: 12,
  ...overrides,
});

describe('ProjectTable', () => {
  it('shows audit progress for auditing projects', () => {
    render(
      <MemoryRouter>
        <ProjectTable
          projects={[buildProject()]}
          categories={categories}
          loadError=""
          statusMap={statusMap}
          onDelete={() => {}}
          onEdit={() => {}}
          onCreateClick={() => {}}
        />
      </MemoryRouter>,
    );

    expect(screen.getAllByText('审核中 12%').length).toBeGreaterThan(0);
    expect(screen.queryByText('AI 分析图纸关系')).not.toBeInTheDocument();
  });
});
