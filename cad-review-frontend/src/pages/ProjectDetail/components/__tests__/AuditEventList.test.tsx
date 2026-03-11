import { fireEvent, render, screen } from '@testing-library/react';
import { vi } from 'vitest';
import AuditEventList from '../AuditEventList';
import type { AuditEvent } from '@/types/api';

const buildEvent = (overrides: Partial<AuditEvent> = {}): AuditEvent => ({
  id: 1,
  audit_version: 1,
  level: 'info',
  step_key: 'task_planning',
  agent_key: 'master_planner_agent',
  agent_name: '总控规划Agent',
  event_kind: 'phase_event',
  progress_hint: 18,
  message: '开始整理图纸',
  created_at: '2026-03-10T10:00:00',
  meta: {},
  ...overrides,
});

describe('AuditEventList', () => {
  it('renders model_stream_delta in process view', () => {
    render(
      <AuditEventList
        events={[
          buildEvent({ id: 1, message: '开始规划', event_kind: 'phase_event' }),
          buildEvent({ id: 2, message: '先整理目录，再检查跨图关系。', event_kind: 'model_stream_delta' }),
        ]}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: '开发者模式' }));

    expect(screen.getByText('先整理目录，再检查跨图关系。')).toBeInTheDocument();
  });

  it('does not show raw model output in default view', () => {
    render(
      <AuditEventList
        events={[
          buildEvent({ id: 1, message: '开始规划', event_kind: 'phase_event' }),
          buildEvent({ id: 2, message: '这是原始模型片段', event_kind: 'model_stream_delta' }),
        ]}
      />,
    );

    expect(screen.getByText('关键进展')).toBeInTheDocument();
    expect(screen.queryByText('terminal://audit-stream')).not.toBeInTheDocument();
    expect(screen.queryByText('这是原始模型片段')).not.toBeInTheDocument();
    expect(screen.getByText('开始规划')).toBeInTheDocument();
  });

  it('renders runner broadcasts in default stream view', () => {
    render(
      <AuditEventList
        events={[
          buildEvent({ id: 1, message: '开始规划', event_kind: 'phase_event' }),
          buildEvent({
            id: 2,
            message: '{"raw":"provider fragment"}',
            event_kind: 'provider_stream_delta',
          }),
          buildEvent({
            id: 3,
            message: '关系审查Agent 正在复核第 15 组候选关系，当前核对 A-15 和 A-16',
            event_kind: 'runner_broadcast',
            meta: { stream_layer: 'user_facing', candidate_index: 15 },
          }),
        ]}
      />,
    );

    expect(screen.getByText(/正在复核第 15 组候选关系/)).toBeInTheDocument();
    expect(screen.queryByText('{"raw":"provider fragment"}')).not.toBeInTheDocument();
  });

  it('summarizes parallel relationship work into one user-facing card', () => {
    render(
      <AuditEventList
        events={[
          buildEvent({
            id: 1,
            step_key: 'relationship_discovery',
            agent_key: 'relationship_review_agent',
            agent_name: '关系审查Agent',
            event_kind: 'phase_progress',
            progress_hint: 14,
            message: '关系审查Agent 正在处理第 1 组图纸，共 4 组',
            meta: { group_index: 1, group_count: 4 },
          }),
          buildEvent({
            id: 2,
            step_key: 'relationship_discovery',
            agent_key: 'relationship_review_agent',
            agent_name: '关系审查Agent',
            event_kind: 'phase_progress',
            progress_hint: 14,
            message: '关系审查Agent 正在处理第 2 组图纸，共 4 组',
            meta: { group_index: 2, group_count: 4 },
          }),
          buildEvent({
            id: 3,
            step_key: 'relationship_discovery',
            agent_key: 'relationship_review_agent',
            agent_name: '关系审查Agent',
            event_kind: 'phase_progress',
            progress_hint: 14,
            message: '关系审查Agent 正在处理第 3 组图纸，共 4 组',
            meta: { group_index: 3, group_count: 4 },
          }),
          buildEvent({
            id: 4,
            step_key: 'relationship_discovery',
            agent_key: 'relationship_review_agent',
            agent_name: '关系审查Agent',
            event_kind: 'runner_broadcast',
            progress_hint: 15,
            message: '关系审查Agent 正在整理值得继续复核的候选关系',
            meta: { stream_layer: 'user_facing', mode: 'legacy_group' },
          }),
          buildEvent({
            id: 5,
            step_key: 'relationship_discovery',
            agent_key: 'relationship_review_agent',
            agent_name: '关系审查Agent',
            event_kind: 'phase_progress',
            progress_hint: 14,
            message: '关系审查Agent 正在处理第 4 组图纸，共 4 组',
            meta: { group_index: 4, group_count: 4 },
          }),
        ]}
      />,
    );

    expect(screen.getByText('关系审查中，当前并行 4 组')).toBeInTheDocument();
    expect(screen.getByText('关系审查Agent 正在处理第 4 组图纸，共 4 组')).toBeInTheDocument();
    expect(screen.queryAllByText(/关系审查Agent 正在处理第 [123] 组图纸/)).toHaveLength(0);
  });

  it('summarizes parallel material work for other agents too', () => {
    render(
      <AuditEventList
        events={[
          buildEvent({
            id: 1,
            step_key: 'material',
            agent_key: 'material_review_agent',
            agent_name: '材料审查Agent',
            event_kind: 'runner_broadcast',
            progress_hint: 36,
            message: '材料审查Agent 正在继续推进当前审图步骤',
            meta: { sheet_no: 'M-01' },
          }),
          buildEvent({
            id: 2,
            step_key: 'material',
            agent_key: 'material_review_agent',
            agent_name: '材料审查Agent',
            event_kind: 'runner_broadcast',
            progress_hint: 36,
            message: '材料审查Agent 正在继续推进当前审图步骤',
            meta: { sheet_no: 'M-02' },
          }),
          buildEvent({
            id: 3,
            step_key: 'material',
            agent_key: 'material_review_agent',
            agent_name: '材料审查Agent',
            event_kind: 'runner_broadcast',
            progress_hint: 36,
            message: '材料审查Agent 正在继续推进当前审图步骤',
            meta: { sheet_no: 'M-03' },
          }),
        ]}
      />,
    );

    expect(screen.getByText('材料审查中，当前并行 3 张图纸')).toBeInTheDocument();
  });

  it('pauses auto-scroll when user scrolls up', () => {
    Object.defineProperty(HTMLElement.prototype, 'scrollTo', {
      configurable: true,
      value: vi.fn(),
    });
    const scrollSpy = vi.spyOn(HTMLElement.prototype, 'scrollTo').mockImplementation(() => {});
    const initialEvents = Array.from({ length: 3 }, (_, index) =>
      buildEvent({ id: index + 1, message: `事件 ${index + 1}` }),
    );
    const { rerender, container } = render(<AuditEventList events={initialEvents} />);
    scrollSpy.mockClear();
    const viewport = container.querySelector('[data-testid=\"audit-event-scroll\"]') as HTMLDivElement;

    Object.defineProperty(viewport, 'scrollHeight', { configurable: true, value: 1000 });
    Object.defineProperty(viewport, 'clientHeight', { configurable: true, value: 200 });
    Object.defineProperty(viewport, 'scrollTop', { configurable: true, value: 100 });

    fireEvent.scroll(viewport);

    rerender(
      <AuditEventList
        events={[...initialEvents, buildEvent({ id: 4, message: '事件 4' })]}
      />,
    );

    expect(scrollSpy).not.toHaveBeenCalled();
    scrollSpy.mockRestore();
  });

  it('merges repeated heartbeat and retry events into one line', () => {
    render(
      <AuditEventList
        events={[
          buildEvent({
            id: 1,
            level: 'warning',
            event_kind: 'heartbeat',
            message: '第 3 组图纸分析时间较长，系统仍在继续',
            meta: { group_index: 3, group_count: 10 },
          }),
          buildEvent({
            id: 2,
            level: 'warning',
            event_kind: 'heartbeat',
            message: '第 3 组图纸分析时间较长，系统仍在继续',
            meta: { group_index: 3, group_count: 10 },
          }),
          buildEvent({
            id: 3,
            level: 'warning',
            event_kind: 'phase_event',
            message: 'AI 引擎流式连接短暂中断，正在第 1 次重试',
            meta: { mode: 'pair_compare', source_sheet_no: 'A1.01', target_sheet_no: 'A4.01', reason: '429' },
          }),
          buildEvent({
            id: 4,
            level: 'warning',
            event_kind: 'phase_event',
            message: 'AI 引擎流式连接短暂中断，正在第 2 次重试',
            meta: { mode: 'pair_compare', source_sheet_no: 'A1.01', target_sheet_no: 'A4.01', reason: '429' },
          }),
        ]}
      />,
    );

    expect(screen.getAllByText(/连续提醒 2 次/)).toHaveLength(2);
    expect(screen.getByText(/第 2 次重试（连续提醒 2 次）/)).toBeInTheDocument();
    expect(screen.getAllByText('retry')).toHaveLength(1);
  });
});
