import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, beforeEach, expect, it, vi } from 'vitest';
import AuditLogsPage from '../AuditLogsPage';
import type { AuditStatus, CatalogItem, Project, AuditResult } from '@/types';
import type { AuditEvent, AuditHistoryItem } from '@/types/api';

const mockGetProject = vi.fn();
const mockGetAuditStatus = vi.fn();
const mockGetAuditHistory = vi.fn();
const mockGetCatalog = vi.fn();
const mockGetAuditEvents = vi.fn();
const mockGetAuditResults = vi.fn();

const mockCreateAuditEventStreamController = vi.fn();
const mockCreateAuditResultStreamController = vi.fn();

vi.mock('@/api', () => ({
  getProject: (...args: unknown[]) => mockGetProject(...args),
  getAuditStatus: (...args: unknown[]) => mockGetAuditStatus(...args),
  getAuditHistory: (...args: unknown[]) => mockGetAuditHistory(...args),
  getCatalog: (...args: unknown[]) => mockGetCatalog(...args),
  getAuditEvents: (...args: unknown[]) => mockGetAuditEvents(...args),
  getAuditResults: (...args: unknown[]) => mockGetAuditResults(...args),
}));

vi.mock('@/pages/ProjectDetail/components/auditEventStream', () => ({
  createAuditEventStreamController: (...args: unknown[]) => mockCreateAuditEventStreamController(...args),
}));

vi.mock('@/pages/ProjectDetail/components/auditResultStream', () => ({
  createAuditResultStreamController: (...args: unknown[]) => mockCreateAuditResultStreamController(...args),
}));

const buildProject = (): Project => ({
  id: 'proj-1',
  name: '测试项目',
  category: null,
  tags: null,
  description: null,
  cache_version: 1,
  created_at: '2026-03-13T09:00:00',
  status: 'auditing',
  updated_at: '2026-03-13T10:00:00',
  current_step: '审图内核派发副审任务',
  progress: 62,
});

const buildStatus = (): AuditStatus => ({
  project_id: 'proj-1',
  status: 'auditing',
  audit_version: 3,
  current_step: '审图内核复核冲突结果',
  progress: 88,
  total_issues: 1,
  run_status: 'running',
  provider_mode: 'sdk',
  error: null,
  started_at: '2026-03-13T10:00:00',
  finished_at: null,
  scope_mode: null,
  scope_summary: null,
  ui_runtime: {
    chief: {
      title: '审图内核',
      current_action: '审图内核正在复核冲突结果',
      summary: '已派发 1 张副审任务卡',
      assigned_task_count: 1,
      active_worker_count: 1,
      completed_worker_count: 0,
      blocked_worker_count: 0,
      queued_task_count: 0,
      issue_count: 1,
      updated_at: '2026-03-13T10:01:00',
    },
    final_review: {
      current_assignment_title: 'A1.06 -> A2.00',
      current_action: '终审完成 asg-1：accepted（llm）',
      summary: '已通过 1 条',
      accepted_count: 1,
      needs_more_evidence_count: 0,
      redispatch_count: 0,
      updated_at: '2026-03-13T10:02:00',
    },
    organizer: {
      current_action: '审图内核 Agent 已整理完成审核报告，共汇总 1 处问题',
      summary: '已整理 1 条最终问题。',
      accepted_issue_count: 1,
      current_section: null,
      updated_at: '2026-03-13T10:03:00',
    },
    worker_sessions: [
      {
        session_key: 'assignment:asg-1',
        worker_name: '标高副审',
        skill_id: 'elevation_consistency',
        skill_label: '标高一致性 Skill',
        task_title: '核对 A1.06 与 A2.00 标高',
        current_action: '正在核对标高',
        status: 'active',
        updated_at: '2026-03-13T10:01:30',
        context: {
          source_sheet_no: 'A1.06',
          target_sheet_no: 'A2.00',
          sheet_no: null,
        },
        recent_actions: [],
      },
    ],
    recent_completed: [],
  },
});

const buildHistory = (): AuditHistoryItem[] => ([
  {
    version: 3,
    status: 'running',
    count: 1,
    grouped_count: 1,
    types: { dimension: 1 },
    started_at: '2026-03-13T10:00:00',
    finished_at: null,
  },
  {
    version: 2,
    status: 'done',
    count: 1,
    grouped_count: 1,
    types: { index: 1 },
    started_at: '2026-03-13T08:00:00',
    finished_at: '2026-03-13T08:10:00',
  },
]);

const buildCatalog = (): CatalogItem[] => ([
  {
    id: 'c1',
    project_id: 'proj-1',
    sheet_no: 'A1.06',
    sheet_name: '一层平面',
    version: null,
    date: null,
    status: 'active',
    sort_order: 1,
  },
  {
    id: 'c2',
    project_id: 'proj-1',
    sheet_no: 'A2.00',
    sheet_name: '立面图',
    version: null,
    date: null,
    status: 'active',
    sort_order: 2,
  },
]);

const v3WorkerEvent: AuditEvent = {
  id: 101,
  audit_version: 3,
  level: 'success',
  step_key: 'dimension',
  agent_key: 'elevation_consistency_agent',
  agent_name: '副审 Agent',
  event_kind: 'worker_assignment_completed',
  progress_hint: 60,
  message: '副审完成 asg-1',
  created_at: '2026-03-13T10:01:30',
  meta: {
    actor_role: 'worker',
    assignment_id: 'asg-1',
    summary: '副审结论摘要',
    confidence: 0.91,
    markdown_conclusion: '### 结论\n- A1.06 与 A2.00 标高不一致',
    evidence_bundle: { anchors: [{ sheet_no: 'A1.06' }] },
  },
};

const v3FinalReviewEvent: AuditEvent = {
  id: 102,
  audit_version: 3,
  level: 'success',
  step_key: 'chief_review',
  agent_key: 'chief_review_agent',
  agent_name: '审图内核 Agent',
  event_kind: 'final_review_decision',
  progress_hint: 90,
  message: '终审完成 asg-1：accepted（llm）',
  created_at: '2026-03-13T10:02:00',
  meta: {
    actor_role: 'chief',
    assignment_id: 'asg-1',
    decision: 'accepted',
    decision_source: 'llm',
    rationale: '证据完整',
  },
};

const v2ChiefEvent: AuditEvent = {
  id: 201,
  audit_version: 2,
  level: 'info',
  step_key: 'task_planning',
  agent_key: 'chief_review_agent',
  agent_name: '审图内核 Agent',
  event_kind: 'phase_completed',
  progress_hint: 18,
  message: 'v2 审图内核历史输出',
  created_at: '2026-03-13T08:02:00',
  meta: { actor_role: 'chief' },
};

const v3RawRow: AuditResult = {
  id: 'issue-v3-1',
  project_id: 'proj-1',
  audit_version: 3,
  type: 'dimension',
  severity: 'warning',
  sheet_no_a: 'A1.06',
  sheet_no_b: 'A2.00',
  location: '入口立面',
  value_a: null,
  value_b: null,
  rule_id: null,
  finding_type: null,
  finding_status: 'confirmed',
  source_agent: 'organizer_agent',
  evidence_pack_id: null,
  review_round: 1,
  triggered_by: null,
  confidence: 0.91,
  description: 'v3 标高不一致',
  evidence_json: '{"anchors":[{"sheet_no":"A1.06"}]}',
  locations: ['入口立面'],
  occurrence_count: 1,
  is_resolved: false,
  resolved_at: null,
  feedback_status: 'none',
  feedback_at: null,
  feedback_note: null,
  is_grouped: false,
  group_id: null,
  issue_ids: [],
};

const v2RawRow: AuditResult = {
  ...v3RawRow,
  id: 'issue-v2-1',
  audit_version: 2,
  type: 'index',
  description: 'v2 索引问题',
};

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/projects/proj-1/audit-logs']}>
      <Routes>
        <Route path="/projects/:id/audit-logs" element={<AuditLogsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('AuditLogsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();

    mockGetProject.mockResolvedValue(buildProject());
    mockGetAuditStatus.mockResolvedValue(buildStatus());
    mockGetAuditHistory.mockResolvedValue(buildHistory());
    mockGetCatalog.mockResolvedValue(buildCatalog());
    mockGetAuditEvents.mockImplementation((_projectId: string, params?: { version?: number }) => {
      const version = params?.version;
      if (version === 2) {
        return Promise.resolve({ items: [v2ChiefEvent], next_since_id: 201 });
      }
      return Promise.resolve({ items: [v3WorkerEvent, v3FinalReviewEvent], next_since_id: 102 });
    });
    mockGetAuditResults.mockImplementation((_projectId: string, params?: { version?: number; view?: 'grouped' | 'raw' }) => {
      if (params?.view === 'raw' && params?.version === 2) {
        return Promise.resolve([v2RawRow]);
      }
      if (params?.view === 'raw') {
        return Promise.resolve([v3RawRow]);
      }
      return Promise.resolve([]);
    });

    mockCreateAuditEventStreamController.mockImplementation((options: any) => ({
      start: () => {
        if (options.version === 2) {
          options.onEvents([v2ChiefEvent]);
        } else {
          options.onEvents([v3WorkerEvent, v3FinalReviewEvent]);
        }
      },
      stop: vi.fn(),
      getLastEventId: () => 0,
    }));

    mockCreateAuditResultStreamController.mockImplementation((options: any) => ({
      start: () => {
        if (options.version === 2) {
          options.onUpsert({ row: v2RawRow, rawRows: [v2RawRow], counts: null, sourceIssueIds: ['issue-v2-1'] });
        } else {
          options.onUpsert({ row: v3RawRow, rawRows: [v3RawRow], counts: null, sourceIssueIds: ['issue-v3-1'] });
        }
      },
      stop: vi.fn(),
      getLastEventId: () => 0,
    }));
  });

  it('在一个页面渲染四分区并且每区可滚动', async () => {
    renderPage();

    await screen.findByText('审图内核');
    expect(screen.getByText('副审')).toBeInTheDocument();
    expect(screen.getByText('终审')).toBeInTheDocument();
    expect(screen.getByText('最终问题实时预览（逐条）')).toBeInTheDocument();

    expect(screen.getByTestId('chief-scroll')).toHaveClass('overflow-auto');
    expect(screen.getByTestId('worker-scroll')).toHaveClass('overflow-auto');
    expect(screen.getByTestId('final-review-scroll')).toHaveClass('overflow-auto');
    expect(screen.getByTestId('issues-scroll')).toHaveClass('overflow-auto');
  });

  it('能把副审完成、终审决策、raw_rows 解析到对应分区', async () => {
    renderPage();

    fireEvent.click(await screen.findByText('查看完整结论 + 证据'));
    await screen.findByText(/副审结论摘要/);
    expect(screen.getAllByText('终审完成 asg-1：accepted（llm）').length).toBeGreaterThan(0);
    expect(screen.getByText('v3 标高不一致')).toBeInTheDocument();
  });

  it('切换版本后会清空旧流状态并按新版本重新订阅', async () => {
    renderPage();
    await screen.findByText('v3 标高不一致');

    const select = screen.getByTestId('version-select');
    fireEvent.change(select, { target: { value: '2' } });

    await screen.findByText('v2 审图内核历史输出');
    await screen.findByText('v2 索引问题');
    await waitFor(() => {
      expect(screen.queryByText('v3 标高不一致')).not.toBeInTheDocument();
    });

    const calledVersions = mockCreateAuditEventStreamController.mock.calls.map((call) => call[0].version);
    expect(calledVersions).toContain(3);
    expect(calledVersions).toContain(2);
  });
});
