import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, vi } from 'vitest';
import ProjectStepAudit from '../project-detail/ProjectStepAudit';
import type { AuditResult, AuditStatus } from '@/types';

const mockCreateFeedbackThread = vi.fn();
const mockGetFeedbackThreadByResult = vi.fn();
const mockAppendFeedbackThreadMessage = vi.fn();
const mockListFeedbackThreadsByResults = vi.fn();
const streamControllerOptions: any[] = [];
const mockCreateFeedbackThreadStreamController = vi.fn(() => ({
  start: vi.fn(),
  stop: vi.fn(),
  getLastEventId: vi.fn(() => 0),
}));

vi.mock('@/api', () => ({
  downloadPdfReport: vi.fn(() => '#'),
  getDrawingImageUrl: vi.fn(() => '#'),
  getFeedbackAttachmentUrl: vi.fn((value: string) => value),
  getAuditResultPreview: vi.fn(),
  batchAuditResultPreview: vi.fn(),
  updateAuditResult: vi.fn(),
  batchUpdateAuditResults: vi.fn(),
  listFeedbackThreadsByResults: (...args: any[]) => mockListFeedbackThreadsByResults(...args),
  createFeedbackThread: (...args: any[]) => mockCreateFeedbackThread(...args),
  getFeedbackThreadByResult: (...args: any[]) => mockGetFeedbackThreadByResult(...args),
  appendFeedbackThreadMessage: (...args: any[]) => mockAppendFeedbackThreadMessage(...args),
}));

vi.mock('../feedbackThreadStream', () => ({
  createFeedbackThreadStreamController: (...args: any[]) => {
    streamControllerOptions.push(args[0]);
    return mockCreateFeedbackThreadStreamController(...args);
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
  confidence: 0.52,
  description: '索引指向疑似不一致',
  evidence_json: '{"anchors":[]}',
  locations: ['索引1'],
  occurrence_count: 1,
  is_resolved: false,
  resolved_at: null,
  feedback_status: 'none',
  feedback_at: null,
  feedback_note: null,
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

describe('FeedbackThreadDrawer integration', () => {
  beforeEach(() => {
    streamControllerOptions.length = 0;
    vi.stubGlobal('URL', {
      createObjectURL: vi.fn(() => 'blob:preview'),
      revokeObjectURL: vi.fn(),
    });
  });

  it('opens feedback drawer and shows agent reply after sending message', async () => {
    mockListFeedbackThreadsByResults.mockResolvedValueOnce([]);
    mockGetFeedbackThreadByResult.mockRejectedValueOnce({ response: { status: 404 } });
    mockCreateFeedbackThread.mockResolvedValueOnce({
      id: 'thread-1',
      project_id: 'proj-1',
      audit_result_id: 'result-1',
      audit_version: 1,
      status: 'agent_reviewing',
      learning_decision: 'pending',
      agent_decision: null,
      agent_confidence: null,
      opened_by: 'user',
      source_agent: 'index_review_agent',
      rule_id: 'index_alias_rule',
      issue_type: 'index',
      summary: 'Agent 正在判断这条反馈。',
      resolution_reason: null,
      escalation_reason: null,
      created_at: null,
      updated_at: null,
      closed_at: null,
      messages: [
        { id: 'm1', thread_id: 'thread-1', role: 'user', message_type: 'claim', content: '这是误报', structured_json: null, created_at: null },
      ],
    });

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

    fireEvent.click(screen.getByLabelText(/提交误报反馈/));
    expect(await screen.findByText('反馈会话')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('先说说为什么你觉得这是误报'), {
      target: { value: '这是误报' },
    });
    fireEvent.click(screen.getByRole('button', { name: '发送给 Agent' }));

    await waitFor(() => expect(mockCreateFeedbackThread).toHaveBeenCalled());
    await waitFor(() => expect(mockCreateFeedbackThreadStreamController).toHaveBeenCalledWith(expect.objectContaining({
      projectId: 'proj-1',
      version: 1,
      threadId: 'thread-1',
    })));
    expect((await screen.findAllByText('Agent 正在判断')).length).toBeGreaterThan(0);
    expect(screen.getByText('误报反馈Agent 正在思考...')).toBeInTheDocument();

    const threadStreamOptions = streamControllerOptions.find((item) => item.threadId === 'thread-1');
    await act(async () => {
      threadStreamOptions.onThreadUpsert?.({
        id: 'thread-1',
        project_id: 'proj-1',
        audit_result_id: 'result-1',
        audit_version: 1,
        status: 'agent_needs_user_input',
        learning_decision: 'pending',
        agent_decision: 'agent_needs_user_input',
        agent_confidence: 0.52,
        opened_by: 'user',
        source_agent: 'index_review_agent',
        rule_id: 'index_alias_rule',
        issue_type: 'index',
        summary: '用户反馈过于笼统，暂时无法直接判断是否为误报。',
        resolution_reason: null,
        escalation_reason: null,
        created_at: null,
        updated_at: null,
        closed_at: null,
        messages: [
          { id: 'm1', thread_id: 'thread-1', role: 'user', message_type: 'claim', content: '这是误报', structured_json: null, created_at: null },
          { id: 'm2', thread_id: 'thread-1', role: 'agent', message_type: 'question', content: '你可以补一句这张图在项目里的常用叫法、别名，或为什么你判断它其实指向同一张图吗？', structured_json: null, created_at: null },
        ],
      });
      threadStreamOptions.onMessageCreated?.({
        id: 'm3',
        thread_id: 'thread-1',
        role: 'agent',
        message_type: 'note',
        content: '这是抽屉线程流追加的新消息。',
        structured_json: null,
        created_at: null,
      }, { threadId: 'thread-1' });
    });

    expect(await screen.findByText('这是抽屉线程流追加的新消息。')).toBeInTheDocument();
  });

  it('uses grouped row id instead of first issue id when opening grouped feedback thread', async () => {
    mockListFeedbackThreadsByResults.mockResolvedValueOnce([]);
    mockGetFeedbackThreadByResult.mockRejectedValueOnce({ response: { status: 404 } });

    render(
      <ProjectStepAudit
        projectId="proj-1"
        projectStatus="done"
        projectCacheVersion={1}
        auditStatus={auditStatus}
        auditHistory={[]}
        selectedAuditVersion={1}
        auditResults={[buildResult({
          id: 'group_abc',
          is_grouped: true,
          group_id: 'group_abc',
          issue_ids: ['issue-1', 'issue-2'],
        })]}
        drawings={[]}
        stageTitle="审图结果"
        onSelectAuditVersion={vi.fn()}
        onRequestDeleteVersion={vi.fn()}
        onAuditResultsChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByLabelText(/提交误报反馈/));

    await waitFor(() => expect(mockGetFeedbackThreadByResult).toHaveBeenCalledWith(
      'proj-1',
      'group_abc',
      { auditVersion: 1 },
    ));
  });

  it('submits uploaded images together with the feedback message', async () => {
    mockListFeedbackThreadsByResults.mockResolvedValueOnce([]);
    mockGetFeedbackThreadByResult.mockRejectedValueOnce({ response: { status: 404 } });
    mockCreateFeedbackThread.mockResolvedValueOnce({
      id: 'thread-1',
      project_id: 'proj-1',
      audit_result_id: 'result-1',
      audit_version: 1,
      status: 'agent_reviewing',
      learning_decision: 'pending',
      agent_decision: null,
      agent_confidence: null,
      opened_by: 'user',
      source_agent: 'index_review_agent',
      rule_id: 'index_alias_rule',
      issue_type: 'index',
      summary: 'Agent 正在判断这条反馈。',
      resolution_reason: null,
      escalation_reason: null,
      created_at: null,
      updated_at: null,
      closed_at: null,
      messages: [
        { id: 'm1', thread_id: 'thread-1', role: 'user', message_type: 'claim', content: '请结合图片判断', structured_json: null, created_at: null, attachments: [] },
      ],
    });

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

    fireEvent.click(screen.getByLabelText(/提交误报反馈/));
    expect(await screen.findByText('反馈会话')).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText('先说说为什么你觉得这是误报'), {
      target: { value: '请结合图片判断' },
    });

    const fileInput = document.querySelector('input[type="file"]') as HTMLInputElement;
    const file1 = new File(['img-1'], 'proof-1.png', { type: 'image/png' });
    const file2 = new File(['img-2'], 'proof-2.png', { type: 'image/png' });
    fireEvent.change(fileInput, { target: { files: [file1, file2] } });

    fireEvent.click(screen.getByRole('button', { name: '发送给 Agent' }));

    await waitFor(() => expect(mockCreateFeedbackThread).toHaveBeenCalledWith(
      'proj-1',
      'result-1',
      { message: '请结合图片判断', images: [file1, file2] },
      { auditVersion: 1 },
    ));
  });

  it('accepts pasted images but never keeps more than three', async () => {
    mockListFeedbackThreadsByResults.mockResolvedValueOnce([]);
    mockGetFeedbackThreadByResult.mockRejectedValueOnce({ response: { status: 404 } });

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

    fireEvent.click(screen.getByLabelText(/提交误报反馈/));
    expect(await screen.findByText('反馈会话')).toBeInTheDocument();

    const textarea = screen.getByPlaceholderText('先说说为什么你觉得这是误报');
    const files = [
      new File(['1'], 'paste-1.png', { type: 'image/png' }),
      new File(['2'], 'paste-2.png', { type: 'image/png' }),
      new File(['3'], 'paste-3.png', { type: 'image/png' }),
      new File(['4'], 'paste-4.png', { type: 'image/png' }),
    ];

    fireEvent.paste(textarea, {
      clipboardData: {
        items: files.map((file) => ({
          kind: 'file',
          type: 'image/png',
          getAsFile: () => file,
        })),
      },
    });

    expect(screen.getByText('3/3')).toBeInTheDocument();
    expect(screen.getByText('paste-1.png')).toBeInTheDocument();
    expect(screen.getByText('paste-2.png')).toBeInTheDocument();
    expect(screen.getByText('paste-3.png')).toBeInTheDocument();
    expect(screen.queryByText('paste-4.png')).not.toBeInTheDocument();
  });
});
