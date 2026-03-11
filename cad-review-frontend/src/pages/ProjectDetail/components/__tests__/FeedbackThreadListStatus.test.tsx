import { act, render, screen, waitFor } from '@testing-library/react';
import { vi } from 'vitest';
import ProjectStepAudit from '../project-detail/ProjectStepAudit';
import type { AuditResult, AuditStatus } from '@/types';

const mockListFeedbackThreadsByResults = vi.fn();
const mockCreateFeedbackThreadStreamController = vi.fn();
let streamThreadUpsertHandler: ((thread: any) => void) | null = null;

vi.mock('@/api', () => ({
  downloadPdfReport: vi.fn(() => '#'),
  getDrawingImageUrl: vi.fn(() => '#'),
  getAuditResultPreview: vi.fn(),
  batchAuditResultPreview: vi.fn(),
  updateAuditResult: vi.fn(),
  batchUpdateAuditResults: vi.fn(),
  listFeedbackThreadsByResults: (...args: any[]) => mockListFeedbackThreadsByResults(...args),
  getFeedbackThreadByResult: vi.fn(),
  createFeedbackThread: vi.fn(),
  appendFeedbackThreadMessage: vi.fn(),
}));

vi.mock('../feedbackThreadStream', () => ({
  createFeedbackThreadStreamController: (...args: any[]) => {
    mockCreateFeedbackThreadStreamController(...args);
    const options = args[0];
    streamThreadUpsertHandler = options.onThreadUpsert;
    return {
      start: vi.fn(),
      stop: vi.fn(),
      getLastEventId: vi.fn(() => 0),
    };
  },
}));

const buildResult = (overrides: Partial<AuditResult> = {}): AuditResult => ({
  id: 'result-1',
  project_id: 'proj-1',
  audit_version: 1,
  type: 'index',
  severity: 'error',
  sheet_no_a: 'A1.01',
  sheet_no_b: 'A6.01',
  location: '索引1',
  value_a: null,
  value_b: null,
  rule_id: 'index_alias_rule',
  finding_type: 'missing_ref',
  finding_status: 'confirmed',
  source_agent: 'index_review_agent',
  evidence_pack_id: null,
  review_round: 1,
  triggered_by: null,
  confidence: 0.78,
  description: '索引指向疑似不一致',
  evidence_json: '{"anchors":[]}',
  locations: ['索引1'],
  occurrence_count: 1,
  is_resolved: false,
  resolved_at: null,
  feedback_status: 'incorrect',
  feedback_at: null,
  feedback_note: '项目里是别名',
  is_grouped: false,
  group_id: null,
  issue_ids: ['result-1'],
  ...overrides,
});

const auditStatus: AuditStatus = {
  project_id: 'proj-1',
  status: 'done',
  audit_version: 1,
  current_step: 'done',
  progress: 100,
  total_issues: 1,
  run_status: 'done',
  provider_mode: 'kimi_sdk',
  error: null,
  started_at: null,
  finished_at: null,
  scope_mode: 'full',
  scope_summary: null,
};

describe('FeedbackThread list status', () => {
  it('shows thread resolution and learning decision in table cell', async () => {
    mockListFeedbackThreadsByResults.mockResolvedValueOnce([
      {
        id: 'thread-1',
        project_id: 'proj-1',
        audit_result_id: 'result-1',
        result_group_id: null,
        audit_version: 1,
        status: 'resolved_incorrect',
        learning_decision: 'record_only',
        agent_decision: 'resolved_incorrect',
        agent_confidence: 0.78,
        opened_by: 'user',
        source_agent: 'index_review_agent',
        rule_id: 'index_alias_rule',
        issue_type: 'index',
        summary: '这条反馈更像是命名别名导致的误报。',
        resolution_reason: null,
        escalation_reason: null,
        created_at: null,
        updated_at: null,
        closed_at: null,
        messages: [],
      },
    ]);

    render(
      <ProjectStepAudit
        projectId="proj-1"
        projectStatus="done"
        projectCacheVersion={1}
        auditStatus={auditStatus}
        auditHistory={[]}
        selectedAuditVersion={1}
        auditResults={[buildResult()]}
        drawings={[]}
        stageTitle="审图结果"
        onSelectAuditVersion={vi.fn()}
        onRequestDeleteVersion={vi.fn()}
        onAuditResultsChange={vi.fn()}
      />,
    );

    await waitFor(() => expect(mockListFeedbackThreadsByResults).toHaveBeenCalled());
    expect(mockListFeedbackThreadsByResults).toHaveBeenCalledWith('proj-1', ['result-1'], { auditVersion: 1 });
    expect(mockCreateFeedbackThreadStreamController).toHaveBeenCalledWith(expect.objectContaining({
      projectId: 'proj-1',
      version: 1,
    }));
    expect(mockCreateFeedbackThreadStreamController).toHaveBeenCalledWith(expect.not.objectContaining({
      threadId: expect.anything(),
    }));
    expect(await screen.findByText('已判定为误报')).toBeInTheDocument();
    expect(await screen.findByText('仅记录，不学习')).toBeInTheDocument();
  });

  it('updates list status when feedback SSE pushes a thread update', async () => {
    mockListFeedbackThreadsByResults.mockReset();
    mockListFeedbackThreadsByResults.mockResolvedValueOnce([]);

    render(
      <ProjectStepAudit
        projectId="proj-1"
        projectStatus="done"
        projectCacheVersion={1}
        auditStatus={auditStatus}
        auditHistory={[]}
        selectedAuditVersion={1}
        auditResults={[buildResult({ feedback_status: 'none', feedback_note: null })]}
        drawings={[]}
        stageTitle="审图结果"
        onSelectAuditVersion={vi.fn()}
        onRequestDeleteVersion={vi.fn()}
        onAuditResultsChange={vi.fn()}
      />,
    );

    await waitFor(() => expect(mockListFeedbackThreadsByResults).toHaveBeenCalledTimes(1));
    expect(mockCreateFeedbackThreadStreamController).toHaveBeenCalled();
    act(() => {
      streamThreadUpsertHandler?.({
        id: 'thread-2',
        project_id: 'proj-1',
        audit_result_id: 'result-1',
        result_group_id: null,
        audit_version: 1,
        status: 'resolved_incorrect',
        learning_decision: 'record_only',
        agent_decision: 'resolved_incorrect',
        agent_confidence: 0.82,
        opened_by: 'user',
        source_agent: 'index_review_agent',
        rule_id: 'index_alias_rule',
        issue_type: 'index',
        summary: '这是项目里的别名误报。',
        resolution_reason: null,
        escalation_reason: null,
        created_at: null,
        updated_at: null,
        closed_at: null,
        messages: [],
      });
    });
    expect(await screen.findByText('已判定为误报')).toBeInTheDocument();
  });
});
