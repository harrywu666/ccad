import { render, screen } from '@testing-library/react';
import FeedbackThreadDrawer from '../project-detail/FeedbackThreadDrawer';
import type { AuditResult } from '@/types';

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

describe('FeedbackThread status presentation', () => {
  it('renders separate issue resolution and learning decisions', () => {
    render(
      <FeedbackThreadDrawer
        open
        onOpenChange={() => {}}
        result={buildResult()}
        thread={{
          id: 'thread-1',
          project_id: 'proj-1',
          audit_result_id: 'result-1',
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
        }}
        loading={false}
        submitting={false}
        error=""
        onSubmitMessage={async () => {}}
      />,
    );

    expect(screen.getByText('已判定为误报')).toBeInTheDocument();
    expect(screen.getByText('仅记录，不学习')).toBeInTheDocument();
  });

  it('renders needs-user-input state in plain language', () => {
    render(
      <FeedbackThreadDrawer
        open
        onOpenChange={() => {}}
        result={buildResult({ feedback_status: 'none', feedback_note: null })}
        thread={{
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
          messages: [],
        }}
        loading={false}
        submitting={false}
        error=""
        onSubmitMessage={async () => {}}
      />,
    );

    expect(screen.getByText('还需要你补一句')).toBeInTheDocument();
  });

  it('renders agent-unavailable state in plain language', () => {
    render(
      <FeedbackThreadDrawer
        open
        onOpenChange={() => {}}
        result={buildResult({ feedback_status: 'none', feedback_note: null })}
        thread={{
          id: 'thread-1',
          project_id: 'proj-1',
          audit_result_id: 'result-1',
          audit_version: 1,
          status: 'agent_unavailable',
          learning_decision: 'pending',
          agent_decision: 'agent_unavailable',
          agent_confidence: null,
          opened_by: 'user',
          source_agent: 'index_review_agent',
          rule_id: 'index_alias_rule',
          issue_type: 'index',
          summary: '误报反馈Agent（OpenRouter）当前未联通，请稍后再试。',
          resolution_reason: null,
          escalation_reason: 'kimi sdk unavailable',
          created_at: null,
          updated_at: null,
          closed_at: null,
          messages: [],
        }}
        loading={false}
        submitting={false}
        error=""
        onSubmitMessage={async () => {}}
      />,
    );

    expect(screen.getByText('Agent 未联通')).toBeInTheDocument();
  });
});
