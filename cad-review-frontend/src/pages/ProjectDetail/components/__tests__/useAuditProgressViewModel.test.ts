import { describe, expect, it } from 'vitest';
import type { AuditStatus } from '@/types';
import type { AuditEvent } from '@/types/api';
import { buildAuditProgressViewModel } from '../useAuditProgressViewModel';

const buildEvent = (overrides: Partial<AuditEvent> = {}): AuditEvent => ({
  id: 1,
  audit_version: 1,
  level: 'info',
  step_key: 'task_planning',
  agent_key: 'master_planner_agent',
  agent_name: '总控规划Agent',
  event_kind: 'phase_progress',
  progress_hint: 18,
  message: '总控规划Agent 正在生成审核任务图',
  created_at: '2026-03-10T10:00:00',
  meta: {},
  ...overrides,
});

const buildStatus = (overrides: Partial<AuditStatus> = {}): AuditStatus => ({
  project_id: 'proj-1',
  status: 'auditing',
  audit_version: 7,
  current_step: '主审派发副审任务',
  progress: 35,
  total_issues: 3,
  run_status: 'running',
  provider_mode: 'kimi_sdk',
  error: null,
  started_at: '2026-03-10T10:00:00',
  finished_at: null,
  scope_mode: null,
  scope_summary: null,
  ui_runtime: {
    chief: {
      title: '主审',
      current_action: '主审 Agent 已派发 10 张副审任务卡',
      summary: '已派发 10 张副审任务卡，当前 2 个副审进行中，1 个已完成。',
      assigned_task_count: 10,
      active_worker_count: 2,
      completed_worker_count: 1,
      blocked_worker_count: 0,
      queued_task_count: 7,
      issue_count: 3,
      updated_at: '2026-03-10T10:03:00',
    },
    final_review: {
      current_assignment_title: 'A101 ↔ A401 节点归属复核',
      current_action: '终审正在复核 asg-2',
      summary: '已复核 3 张 assignment，其中 1 张要求补证据。',
      accepted_count: 2,
      needs_more_evidence_count: 1,
      redispatch_count: 0,
      updated_at: '2026-03-10T10:04:20',
    },
    organizer: {
      current_action: '正在整理终审通过的问题',
      summary: '已通过 2 处问题，正在输出最终问题列表。',
      accepted_issue_count: 2,
      current_section: '最终问题列表',
      updated_at: '2026-03-10T10:04:30',
    },
    worker_sessions: [
      {
        session_key: 'assignment:asg-1',
        worker_name: '标高副审',
        skill_id: 'elevation_consistency',
        skill_label: '标高一致性 Skill',
        task_title: 'A200 标高一致性',
        current_action: '正在抽取单图标高语义',
        status: 'active',
        updated_at: '2026-03-10T10:03:42',
        context: { sheet_no: 'A200' },
        recent_actions: [
          { at: '2026-03-10T10:03:02', label: '调用 Skill', text: '已启动本轮技能执行' },
          { at: '2026-03-10T10:03:42', label: '现场播报', text: '正在抽取单图标高语义' },
        ],
      },
      {
        session_key: 'assignment:asg-2',
        worker_name: '节点归属副审',
        skill_id: 'node_host_binding',
        skill_label: '节点归属 Skill',
        task_title: 'A101 ↔ A401',
        current_action: '等待重试或主审介入',
        status: 'blocked',
        updated_at: '2026-03-10T10:04:12',
        context: { source_sheet_no: 'A101', target_sheet_no: 'A401' },
        recent_actions: [
          { at: '2026-03-10T10:04:12', label: '等待重试', text: '等待重试或主审介入' },
        ],
      },
    ],
    recent_completed: [
      {
        session_key: 'worker_skill:index_reference:A101:A402',
        worker_name: '索引副审',
        skill_id: 'index_reference',
        skill_label: '索引引用 Skill',
        task_title: 'A101 ↔ A402',
        current_action: '已收束并保存输出',
        status: 'completed',
        updated_at: '2026-03-10T10:02:10',
        context: { source_sheet_no: 'A101', target_sheet_no: 'A402' },
        recent_actions: [
          { at: '2026-03-10T10:02:10', label: '保存输出', text: '已收束并保存输出' },
        ],
      },
    ],
  },
  ...overrides,
});

describe('buildAuditProgressViewModel', () => {
  it('maps chief card and worker wall from ui runtime snapshot', () => {
    const viewModel = buildAuditProgressViewModel({
      auditStatus: buildStatus(),
      providerLabel: 'Kimi SDK',
      events: [],
    });

    expect(viewModel.chief.assignedTaskCount).toBe(10);
    expect(viewModel.chief.activeWorkerCount).toBe(2);
    expect(viewModel.workerWall.active).toHaveLength(2);
    expect(viewModel.workerWall.active[0]?.workerName).toBe('标高副审');
    expect(viewModel.workerWall.active[0]?.recentActions[1]?.text).toContain('抽取单图标高语义');
    expect(viewModel.workerWall.recentCompleted).toHaveLength(1);
    expect(viewModel.workerWall.recentCompleted[0]?.status).toBe('completed');
    expect(viewModel.finalReview.currentAssignmentTitle).toContain('A101');
    expect(viewModel.organizer.currentSection).toBe('最终问题列表');
  });

  it('builds pill copy from chief card state', () => {
    const viewModel = buildAuditProgressViewModel({
      auditStatus: buildStatus({ progress: 45, total_issues: 6 }),
      providerLabel: 'Kimi SDK',
      events: [],
    });

    expect(viewModel.pill.label).toContain('主审');
    expect(viewModel.pill.label).toContain('45%');
    expect(viewModel.pill.issueCount).toBe(3);
  });

  it('falls back to event-derived runtime when ui runtime is missing', () => {
    const viewModel = buildAuditProgressViewModel({
      auditStatus: buildStatus({
        current_step: '规划审核任务图',
        progress: 18,
        total_issues: 0,
        ui_runtime: null,
      }),
      providerLabel: 'Kimi SDK',
      events: [
        buildEvent({
          id: 1,
          step_key: 'task_planning',
          agent_key: 'chief_review_agent',
          agent_name: '主审 Agent',
          event_kind: 'phase_completed',
          message: '主审 Agent 已生成 12 张副审任务卡',
        }),
        buildEvent({
          id: 2,
          step_key: 'dimension',
          agent_key: 'dimension_review_agent',
          agent_name: '尺寸审查Agent',
          event_kind: 'runner_broadcast',
          message: '尺寸审查Agent 正在抽取 A200 的单图标高语义',
          meta: {
            actor_role: 'worker',
            turn_kind: 'dimension_sheet_semantic',
            session_key: 'proj-1:7:dimension_review_agent:sheet_semantic:A200',
            skill_id: 'elevation_consistency',
          },
        }),
      ],
    });

    expect(viewModel.chief.assignedTaskCount).toBe(12);
    expect(viewModel.workerWall.active).toHaveLength(1);
    expect(viewModel.workerWall.active[0]?.taskTitle).toBe('图纸 A200');
    expect(viewModel.workerWall.active[0]?.currentAction).toBe('正在抽取单图标高语义');
    expect(viewModel.supportingText).toBe('当前阶段：规划审核任务图');
    expect(viewModel.finalReview.currentAction).toContain('待终审');
    expect(viewModel.organizer.currentAction).toContain('等待终审');
  });

  it('keeps one worker card per assignment even when internal skill actions are many', () => {
    const viewModel = buildAuditProgressViewModel({
      auditStatus: buildStatus({
        ui_runtime: {
          ...buildStatus().ui_runtime!,
          worker_sessions: [
            {
              session_key: 'assignment:asg-1',
              worker_name: '标高副审',
              skill_id: 'elevation_consistency',
              skill_label: '标高一致性 Skill',
              task_title: 'A200 标高一致性',
              current_action: '正在比对跨图尺寸关系',
              status: 'active',
              updated_at: '2026-03-10T10:05:42',
              context: { source_sheet_no: 'A200', target_sheet_no: 'A201' },
              recent_actions: [
                { at: '2026-03-10T10:03:02', label: '调用 Skill', text: '已启动本轮技能执行' },
                { at: '2026-03-10T10:03:42', label: '现场播报', text: '正在抽取单图标高语义' },
                { at: '2026-03-10T10:05:42', label: '现场播报', text: '正在比对跨图尺寸关系' },
              ],
            },
            {
              session_key: 'assignment:asg-2',
              worker_name: '节点归属副审',
              skill_id: 'node_host_binding',
              skill_label: '节点归属 Skill',
              task_title: 'A101 ↔ A401',
              current_action: '正在复核节点归属',
              status: 'active',
              updated_at: '2026-03-10T10:05:50',
              context: { source_sheet_no: 'A101', target_sheet_no: 'A401' },
              recent_actions: [
                { at: '2026-03-10T10:05:50', label: '现场播报', text: '正在复核节点归属' },
              ],
            },
          ],
        },
      }),
      providerLabel: 'Kimi SDK',
      events: [],
    });

    expect(viewModel.workerWall.active).toHaveLength(2);
    expect(viewModel.workerWall.active[0]?.key).toBe('assignment:asg-1');
    expect(viewModel.workerWall.active[1]?.key).toBe('assignment:asg-2');
  });
});
