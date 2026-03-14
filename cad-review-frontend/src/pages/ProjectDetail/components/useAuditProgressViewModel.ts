import { useMemo } from 'react';
import type {
  AuditStatus,
  AuditUiRuntime,
  AuditUiRuntimeAction,
  AuditUiRuntimeContext,
  AuditUiRuntimeFinalReview,
  AuditUiRuntimeOrganizer,
  AuditUiRuntimeWorkerSession,
} from '@/types';
import type { AuditEvent } from '@/types/api';

export type AuditWorkerSessionState = 'active' | 'completed' | 'blocked';

export interface ChiefCardViewModel {
  title: string;
  currentAction: string;
  summary: string;
  assignedTaskCount: number;
  activeWorkerCount: number;
  completedWorkerCount: number;
  blockedWorkerCount: number;
  queuedTaskCount: number;
  issueCount: number;
  updatedAt?: string | null;
}

export interface WorkerSessionCardViewModel {
  key: string;
  workerName: string;
  skillId?: string | null;
  skillLabel: string;
  taskTitle: string;
  currentAction: string;
  status: AuditWorkerSessionState;
  statusLabel: string;
  updatedAt?: string | null;
  context: AuditUiRuntimeContext;
  recentActions: AuditUiRuntimeAction[];
}

export interface FinalReviewCardViewModel {
  currentAssignmentTitle?: string | null;
  currentAction: string;
  summary: string;
  acceptedCount: number;
  needsMoreEvidenceCount: number;
  redispatchCount: number;
  updatedAt?: string | null;
}

export interface OrganizerCardViewModel {
  currentAction: string;
  summary: string;
  acceptedIssueCount: number;
  currentSection?: string | null;
  updatedAt?: string | null;
}

export interface AuditProgressViewModel {
  headline: string;
  supportingText: string;
  providerLabel?: string;
  progress: number;
  startedAt?: string | null;
  chief: ChiefCardViewModel;
  finalReview: FinalReviewCardViewModel;
  organizer: OrganizerCardViewModel;
  workerWall: {
    active: WorkerSessionCardViewModel[];
    recentCompleted: WorkerSessionCardViewModel[];
  };
  debugTimeline: {
    enabled: boolean;
    events: AuditEvent[];
  };
  pill: {
    label: string;
    issueCount: number;
    progress: number;
  };
}

interface BuildAuditProgressViewModelInput {
  auditStatus?: AuditStatus | null;
  events?: AuditEvent[];
  providerLabel?: string;
}

interface WorkerFallbackSnapshot {
  session_key: string;
  worker_name: string;
  skill_id?: string | null;
  skill_label: string;
  task_title: string;
  current_action: string;
  status: AuditWorkerSessionState;
  updated_at?: string | null;
  context: AuditUiRuntimeContext;
  recent_actions: AuditUiRuntimeAction[];
  event_id: number;
  action_priority: number;
}

const RAW_PROCESS_EVENT_KINDS = new Set(['model_stream_delta', 'provider_stream_delta']);
const BLOCKED_EVENT_KINDS = new Set(['runner_turn_deferred', 'runner_session_failed', 'runner_turn_cancelled']);
const COMPLETED_EVENT_KINDS = new Set(['raw_output_saved', 'output_repair_succeeded']);

const HEADLINE_FLOW = [
  { match: ['校验三线匹配', '构建图纸上下文', 'AI 分析图纸关系'], title: '审图内核准备' },
  { match: ['规划审核任务图', '从任务账本恢复总控现场', '审图内核规划副审任务', '审图内核派发副审任务', '主审规划副审任务', '主审派发副审任务'], title: '审图内核派工' },
  { match: ['索引核对', '尺寸核对', '材料核对'], title: '副审执行' },
  { match: ['审图内核复核冲突结果', '主审复核冲突结果'], title: '终审复核' },
  { match: ['审核完成', '审图内核汇总完成', '审图内核完成结果收束', '主审汇总完成', '主审完成结果收束', '生成报告'], title: '汇总整理' },
];

const WORKER_SKILL_LABELS: Record<string, string> = {
  index_reference: '索引引用 Skill',
  material_semantic_consistency: '材料语义一致性 Skill',
  node_host_binding: '节点归属 Skill',
  spatial_consistency: '空间一致性 Skill',
  elevation_consistency: '标高一致性 Skill',
};

const WORKER_NAME_LABELS: Record<string, string> = {
  index_reference: '索引副审',
  material_semantic_consistency: '材料副审',
  node_host_binding: '节点归属副审',
  spatial_consistency: '空间副审',
  elevation_consistency: '标高副审',
};

const ACTION_LABELS: Record<string, string> = {
  runner_turn_started: '调用 Skill',
  runner_broadcast: '现场播报',
  raw_output_saved: '保存输出',
  output_validation_failed: '输出校验',
  output_repair_started: '整理输出',
  output_repair_succeeded: '整理完成',
  runner_turn_deferred: '等待重试',
  runner_session_failed: '执行失败',
  runner_turn_cancelled: '已中断',
};

const ACTION_PRIORITY: Record<string, number> = {
  runner_session_started: 0,
  runner_turn_started: 1,
  runner_broadcast: 3,
  output_validation_failed: 3,
  output_repair_started: 3,
  output_repair_succeeded: 4,
  raw_output_saved: 4,
  runner_turn_deferred: 5,
  runner_session_failed: 5,
  runner_turn_cancelled: 5,
};

function clampProgress(progress?: number | null) {
  return Math.max(0, Math.min(100, progress || 0));
}

function asMeta(meta: unknown): Record<string, unknown> {
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return {};
  return meta as Record<string, unknown>;
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function resolveHeadline(currentStep?: string | null) {
  if (!currentStep) return '审图内核调度现场';
  const matched = HEADLINE_FLOW.find((item) => item.match.some((text) => currentStep.includes(text)));
  return matched ? matched.title : currentStep;
}

function isChiefEvent(event: AuditEvent) {
  const meta = asMeta(event.meta);
  const actorRole = asText(meta.actor_role);
  if (actorRole === 'chief') return true;
  if (actorRole === 'worker') return false;
  const agentKey = asText(event.agent_key);
  const agentName = asText(event.agent_name);
  const agentId = asText(meta.agent_id);
  const message = asText(event.message);
  return agentKey.includes('chief')
    || agentKey.includes('kernel')
    || agentId === 'chief_review'
    || agentId === 'kernel_review'
    || agentName.includes('审图内核')
    || agentName.includes('主审')
    || message.startsWith('审图内核 Agent')
    || message.startsWith('主审 Agent');
}

function resolveSkillId(event: AuditEvent) {
  const meta = asMeta(event.meta);
  const direct = asText(meta.skill_id) || asText(meta.worker_kind) || asText(meta.suggested_worker_kind);
  if (direct) return direct;

  const sessionKey = asText(meta.session_key);
  if (sessionKey.startsWith('worker_skill:')) {
    const parts = sessionKey.split(':');
    if (parts.length >= 2) return parts[1] || '';
  }

  const turnKind = asText(meta.turn_kind);
  const agentName = asText(event.agent_name);
  if (turnKind === 'dimension_sheet_semantic') return 'elevation_consistency';
  if (turnKind === 'dimension_pair_compare') return 'spatial_consistency';
  if (turnKind === 'relationship_candidate_review') return 'node_host_binding';
  if (turnKind.includes('index') || agentName.includes('索引')) return 'index_reference';
  if (turnKind.includes('material') || agentName.includes('材料')) return 'material_semantic_consistency';
  if (agentName.includes('关系')) return 'node_host_binding';
  if (agentName.includes('尺寸')) return 'spatial_consistency';
  return '';
}

function extractSessionKey(event: AuditEvent) {
  const meta = asMeta(event.meta);
  const sessionKey = asText(meta.session_key);
  if (sessionKey) return sessionKey;

  const artifactPath = asText(meta.artifact_path);
  const fileName = artifactPath.split('/').pop() || '';
  const sheetMatch = fileName.match(/sheet_semantic_([^_]+)__\d{8}/);
  if (sheetMatch) return `sheet_semantic:${sheetMatch[1]}`;
  const pairMatch = fileName.match(/pair_compare_([^_]+)_([^_]+)__\d{8}/);
  if (pairMatch) return `pair_compare:${pairMatch[1]}:${pairMatch[2]}`;
  const candidateMatch = fileName.match(/candidate_review_([^_]+)__\d{8}/);
  if (candidateMatch) return `candidate_review:${candidateMatch[1]}`;
  return '';
}

function extractSessionTail(sessionKey: string) {
  const normalized = asText(sessionKey);
  if (!normalized) return [] as string[];
  const parts = normalized.split(':');
  if (normalized.startsWith('worker_skill:')) return parts;
  if (parts.length >= 5) return parts.slice(3);
  return parts;
}

function extractTaskTitle(event: AuditEvent, sessionKey: string) {
  const meta = asMeta(event.meta);
  const sourceSheet = asText(meta.source_sheet_no) || asText(meta.candidate_source_sheet_no);
  const targetSheet = asText(meta.target_sheet_no) || asText(meta.candidate_target_sheet_no);
  const sheetNo = asText(meta.sheet_no);
  if (sourceSheet && targetSheet) return `${sourceSheet} ↔ ${targetSheet}`;
  if (sheetNo) return `图纸 ${sheetNo}`;

  const tail = extractSessionTail(sessionKey);

  if (sessionKey.startsWith('worker_skill:')) {
    const [, , source, targets] = sessionKey.split(':');
    if (source && targets && targets !== 'SELF') return `${source} ↔ ${targets.split('__').join(' / ')}`;
    if (source) return `图纸 ${source}`;
  }
  if ((tail[0] === 'sheet_semantic' || tail[0] === 'dimension_sheet_semantic') && tail[1]) {
    return `图纸 ${tail[1]}`;
  }
  if ((tail[0] === 'pair_compare' || tail[0] === 'dimension_pair_compare') && tail[1] && tail[2]) {
    return `${tail[1]} ↔ ${tail[2]}`;
  }
  if ((tail[0] === 'candidate_review' || tail[0] === 'relationship_candidate_review') && tail[1]) {
    return `候选关系 ${tail[1].slice(0, 8)}`;
  }

  if (sessionKey.startsWith('sheet_semantic:')) {
    const value = sessionKey.split(':')[1];
    return value ? `图纸 ${value}` : '单图语义';
  }
  if (sessionKey.startsWith('pair_compare:')) {
    const [, a, b] = sessionKey.split(':');
    return a && b ? `${a} ↔ ${b}` : '跨图尺寸';
  }
  if (sessionKey.startsWith('candidate_review:')) {
    const value = sessionKey.split(':')[1];
    return value ? `候选关系 ${value.slice(0, 8)}` : '候选关系复核';
  }

  const sheets = asText(event.message).match(/[A-Z]{1,2}\d{3,4}[A-Z]?/g) || [];
  if (sheets.length >= 2) return `${sheets[0]} ↔ ${sheets[1]}`;
  if (sheets.length === 1) return `图纸 ${sheets[0]}`;
  return '副审任务';
}

function resolveWorkerName(event: AuditEvent, skillId: string) {
  if (skillId && WORKER_NAME_LABELS[skillId]) return WORKER_NAME_LABELS[skillId];
  const agentName = asText(event.agent_name);
  if (!agentName) return '副审';
  return agentName.endsWith('Agent') ? agentName.slice(0, -5) : agentName;
}

function resolveSkillLabel(skillId: string) {
  return WORKER_SKILL_LABELS[skillId] || '通用复核 Skill';
}

function resolveCurrentAction(event: AuditEvent, taskTitle: string, skillId: string) {
  const eventKind = asText(event.event_kind);
  const rawMessage = asText(event.message);
  const meta = asMeta(event.meta);
  const turnKind = asText(meta.turn_kind);

  if (eventKind === 'raw_output_saved') return '已收束并保存输出';
  if (eventKind === 'output_validation_failed') return '输出格式待整理';
  if (eventKind === 'output_repair_started') return '正在整理输出格式';
  if (eventKind === 'output_repair_succeeded') return '已整理成标准结果';
  if (eventKind === 'runner_turn_deferred') return '等待重试或审图内核介入';
  if (eventKind === 'runner_session_failed') return '执行失败，等待重试';
  if (eventKind === 'runner_turn_cancelled') return '已被人工中断';
  if (eventKind === 'runner_broadcast') {
    if (skillId === 'elevation_consistency') {
      if (taskTitle.startsWith('图纸 ')) return '正在抽取单图标高语义';
      if (taskTitle.includes('↔')) return '正在比对跨图尺寸关系';
      return '正在推进标高复核';
    }
    if (skillId === 'spatial_consistency') return '正在比对跨图空间关系';
    if (skillId === 'node_host_binding') return '正在复核节点归属';
    if (skillId === 'index_reference') return '正在核对索引引用';
    if (skillId === 'material_semantic_consistency') return '正在核对材料语义';
  }

  if (eventKind === 'runner_turn_started') {
    if (turnKind === 'dimension_sheet_semantic' || turnKind === 'sheet_semantic') return '准备提取单图标高语义';
    if (turnKind === 'dimension_pair_compare' || turnKind === 'pair_compare') return '准备执行跨图尺寸对比';
    if (turnKind === 'relationship_candidate_review' || turnKind === 'candidate_review') return '准备复核候选关系';
    return '已启动本轮技能执行';
  }

  if (rawMessage && !rawMessage.includes('已通过 Runner 发起一次')) return rawMessage;
  return '正在执行副审任务';
}

function buildRecentAction(event: AuditEvent, taskTitle: string, skillId: string): AuditUiRuntimeAction {
  return {
    at: event.created_at,
    label: ACTION_LABELS[asText(event.event_kind)] || '现场更新',
    text: resolveCurrentAction(event, taskTitle, skillId),
  };
}

function buildContext(event: AuditEvent): AuditUiRuntimeContext {
  const meta = asMeta(event.meta);
  const sessionKey = extractSessionKey(event);
  const tail = extractSessionTail(sessionKey);
  let sourceSheetNo = asText(meta.source_sheet_no || meta.candidate_source_sheet_no) || null;
  let targetSheetNo = asText(meta.target_sheet_no || meta.candidate_target_sheet_no) || null;
  let sheetNo = asText(meta.sheet_no) || null;

  if (!sheetNo && (tail[0] === 'sheet_semantic' || tail[0] === 'dimension_sheet_semantic') && tail[1]) {
    sheetNo = tail[1];
  }
  if (!sourceSheetNo && !targetSheetNo && (tail[0] === 'pair_compare' || tail[0] === 'dimension_pair_compare') && tail[1] && tail[2]) {
    sourceSheetNo = tail[1];
    targetSheetNo = tail[2];
  }

  return {
    source_sheet_no: sourceSheetNo,
    target_sheet_no: targetSheetNo,
    sheet_no: sheetNo,
  };
}

function normalizeWorkerCard(session: AuditUiRuntimeWorkerSession): WorkerSessionCardViewModel {
  const statusLabel = session.status === 'active'
    ? '进行中'
    : session.status === 'completed'
      ? '已完成'
      : '阻塞中';

  return {
    key: session.session_key,
    workerName: session.worker_name,
    skillId: session.skill_id || null,
    skillLabel: session.skill_label,
    taskTitle: session.task_title,
    currentAction: session.current_action,
    status: session.status,
    statusLabel,
    updatedAt: session.updated_at,
    context: session.context || {
      source_sheet_no: null,
      target_sheet_no: null,
      sheet_no: null,
    },
    recentActions: session.recent_actions || [],
  };
}

function parseCountFromMessage(events: AuditEvent[], pattern: RegExp) {
  for (const event of [...events].reverse()) {
    const match = pattern.exec(asText(event.message));
    if (match) return Number(match[1] || 0);
  }
  return 0;
}

function buildFallbackRuntime(currentStep: string, events: AuditEvent[], totalIssues: number): AuditUiRuntime {
  const sessions = new Map<string, WorkerFallbackSnapshot>();

  events.forEach((event) => {
    if (RAW_PROCESS_EVENT_KINDS.has(asText(event.event_kind))) return;
    if (isChiefEvent(event)) return;

    const key = extractSessionKey(event);
    if (!key) return;

    const skillId = resolveSkillId(event);
    const taskTitle = extractTaskTitle(event, key);
    const currentAction = resolveCurrentAction(event, taskTitle, skillId);
    const recentAction = buildRecentAction(event, taskTitle, skillId);
    const existing = sessions.get(key);

    let status: AuditWorkerSessionState = existing?.status || 'active';
    const eventKind = asText(event.event_kind);
    if (COMPLETED_EVENT_KINDS.has(eventKind)) {
      status = 'completed';
    } else if (BLOCKED_EVENT_KINDS.has(eventKind)) {
      status = 'blocked';
    } else {
      status = 'active';
    }
    const actionPriority = ACTION_PRIORITY[eventKind] ?? 2;

    const nextSnapshot: WorkerFallbackSnapshot = {
      session_key: key,
      worker_name: resolveWorkerName(event, skillId),
      skill_id: skillId || null,
      skill_label: resolveSkillLabel(skillId),
      task_title: taskTitle,
      current_action: existing && existing.action_priority > actionPriority
        ? existing.current_action
        : currentAction,
      status,
      updated_at: event.created_at,
      context: buildContext(event),
      recent_actions: [...(existing?.recent_actions || []), recentAction].slice(-3),
      event_id: event.id,
      action_priority: Math.max(existing?.action_priority ?? 0, actionPriority),
    };
    sessions.set(key, nextSnapshot);
  });

  const items = [...sessions.values()].sort((left, right) => right.event_id - left.event_id);
  const active = items.filter((item) => item.status !== 'completed');
  const completed = items.filter((item) => item.status === 'completed').slice(0, 6);
  const chiefEvents = events.filter((event) => !RAW_PROCESS_EVENT_KINDS.has(asText(event.event_kind)) && isChiefEvent(event));
  const hypothesisCount = parseCountFromMessage(chiefEvents, /生成\s*(\d+)\s*条待核对怀疑卡/);
  const assignedTaskCount = Math.max(
    parseCountFromMessage(chiefEvents, /生成\s*(\d+)\s*张副审任务卡/),
    items.length,
  );
  const activeWorkerCount = items.filter((item) => item.status === 'active').length;
  const completedWorkerCount = items.filter((item) => item.status === 'completed').length;
  const blockedWorkerCount = items.filter((item) => item.status === 'blocked').length;
  const queuedTaskCount = Math.max(0, assignedTaskCount - activeWorkerCount - completedWorkerCount - blockedWorkerCount);
  const latestChief = chiefEvents[chiefEvents.length - 1];

  const summaryParts: string[] = [];
  if (hypothesisCount > 0) summaryParts.push(`已形成 ${hypothesisCount} 条待核对怀疑卡`);
  if (assignedTaskCount > 0) summaryParts.push(`已派发 ${assignedTaskCount} 张副审任务卡`);
  if (activeWorkerCount > 0) summaryParts.push(`${activeWorkerCount} 个副审进行中`);
  if (completedWorkerCount > 0) summaryParts.push(`${completedWorkerCount} 个副审已完成`);
  if (blockedWorkerCount > 0) summaryParts.push(`${blockedWorkerCount} 个副审待处理`);
  if (queuedTaskCount > 0) summaryParts.push(`${queuedTaskCount} 张任务待启动`);

  const fallbackRuntime: AuditUiRuntime = {
    chief: {
      title: '审图内核',
      current_action: latestChief?.message || (currentStep ? `审图内核正在推进：${currentStep}` : '审图内核正在准备审图任务'),
      summary: summaryParts.join('，') || '审图内核正在组织本轮副审调度。',
      assigned_task_count: assignedTaskCount,
      active_worker_count: activeWorkerCount,
      completed_worker_count: completedWorkerCount,
      blocked_worker_count: blockedWorkerCount,
      queued_task_count: queuedTaskCount,
      issue_count: totalIssues,
      updated_at: latestChief?.created_at || null,
    },
    worker_sessions: active,
    recent_completed: completed,
  };
  return {
    ...fallbackRuntime,
    final_review: buildFallbackFinalReview(currentStep, totalIssues, fallbackRuntime),
    organizer: buildFallbackOrganizer(currentStep, totalIssues, fallbackRuntime),
  };
}

function normalizeChief(uiRuntime: AuditUiRuntime, totalIssues: number): ChiefCardViewModel {
  return {
    title: uiRuntime.chief.title || '审图内核',
    currentAction: uiRuntime.chief.current_action || '审图内核正在组织本轮调度',
    summary: uiRuntime.chief.summary || '审图内核正在组织本轮副审调度。',
    assignedTaskCount: uiRuntime.chief.assigned_task_count || 0,
    activeWorkerCount: uiRuntime.chief.active_worker_count || 0,
    completedWorkerCount: uiRuntime.chief.completed_worker_count || 0,
    blockedWorkerCount: uiRuntime.chief.blocked_worker_count || 0,
    queuedTaskCount: uiRuntime.chief.queued_task_count || 0,
    issueCount: uiRuntime.chief.issue_count || totalIssues,
    updatedAt: uiRuntime.chief.updated_at || null,
  };
}

function buildFallbackFinalReview(
  currentStep: string,
  totalIssues: number,
  uiRuntime: AuditUiRuntime,
): AuditUiRuntimeFinalReview {
  const currentAssignmentTitle = uiRuntime.worker_sessions?.[0]?.task_title
    || uiRuntime.recent_completed?.[0]?.task_title
    || null;

  if (currentStep.includes('复核')) {
    return {
      current_assignment_title: currentAssignmentTitle,
      current_action: '终审正在复核最新回流的 assignment',
      summary: '终审会判断副审结论能否进入最终通过态，并决定是否补证据或补派单。',
      accepted_count: 0,
      needs_more_evidence_count: 0,
      redispatch_count: 0,
      updated_at: uiRuntime.chief.updated_at || null,
    };
  }

  if (currentStep.includes('收束') || currentStep.includes('汇总') || currentStep.includes('报告')) {
    return {
      current_assignment_title: currentAssignmentTitle,
      current_action: '待终审结果已回流，审图内核正在收束通过项',
      summary: '终审已完成本轮裁决，当前正在把通过项交给汇总整理。',
      accepted_count: totalIssues,
      needs_more_evidence_count: 0,
      redispatch_count: 0,
      updated_at: uiRuntime.chief.updated_at || null,
    };
  }

  return {
    current_assignment_title: currentAssignmentTitle,
    current_action: '待终审队列等待中',
    summary: '副审回流后，终审意见会在这里单独展示。',
    accepted_count: 0,
    needs_more_evidence_count: 0,
    redispatch_count: 0,
    updated_at: uiRuntime.chief.updated_at || null,
  };
}

function buildFallbackOrganizer(
  currentStep: string,
  totalIssues: number,
  uiRuntime: AuditUiRuntime,
): AuditUiRuntimeOrganizer {
  if (currentStep.includes('收束') || currentStep.includes('汇总') || currentStep.includes('报告')) {
    return {
      current_action: '正在整理终审通过的问题',
      summary: `已通过 ${totalIssues} 处问题，正在输出最终问题列表。`,
      accepted_issue_count: totalIssues,
      current_section: '最终问题列表',
      updated_at: uiRuntime.chief.updated_at || null,
    };
  }

  return {
    current_action: '等待终审通过后启动汇总',
    summary: '只有终审放行的问题，才会进入最终汇总整理。',
    accepted_issue_count: totalIssues,
    current_section: '待生成',
    updated_at: uiRuntime.chief.updated_at || null,
  };
}

function normalizeFinalReview(
  uiRuntime: AuditUiRuntime,
  totalIssues: number,
  currentStep: string,
): FinalReviewCardViewModel {
  const finalReview = uiRuntime.final_review || buildFallbackFinalReview(currentStep, totalIssues, uiRuntime);
  return {
    currentAssignmentTitle: finalReview.current_assignment_title || null,
    currentAction: finalReview.current_action || '待终审队列等待中',
    summary: finalReview.summary || '副审回流后，终审意见会在这里单独展示。',
    acceptedCount: finalReview.accepted_count || 0,
    needsMoreEvidenceCount: finalReview.needs_more_evidence_count || 0,
    redispatchCount: finalReview.redispatch_count || 0,
    updatedAt: finalReview.updated_at || null,
  };
}

function normalizeOrganizer(
  uiRuntime: AuditUiRuntime,
  totalIssues: number,
  currentStep: string,
): OrganizerCardViewModel {
  const organizer = uiRuntime.organizer || buildFallbackOrganizer(currentStep, totalIssues, uiRuntime);
  return {
    currentAction: organizer.current_action || '等待终审通过后启动汇总',
    summary: organizer.summary || '终审通过的问题会在这里整理成最终报告。',
    acceptedIssueCount: organizer.accepted_issue_count || totalIssues,
    currentSection: organizer.current_section || '待生成',
    updatedAt: organizer.updated_at || null,
  };
}

export function buildAuditProgressViewModel({
  auditStatus,
  events = [],
  providerLabel,
}: BuildAuditProgressViewModelInput): AuditProgressViewModel {
  const currentStep = auditStatus?.current_step || '';
  const progress = clampProgress(auditStatus?.progress);
  const totalIssues = auditStatus?.total_issues || 0;
  const uiRuntime = auditStatus?.ui_runtime || buildFallbackRuntime(currentStep, events, totalIssues);
  const chief = normalizeChief(uiRuntime, totalIssues);
  const finalReview = normalizeFinalReview(uiRuntime, totalIssues, currentStep);
  const organizer = normalizeOrganizer(uiRuntime, totalIssues, currentStep);
  const activeCards = (uiRuntime.worker_sessions || []).map(normalizeWorkerCard);
  const recentCompletedCards = (uiRuntime.recent_completed || []).map(normalizeWorkerCard);

  return {
    headline: resolveHeadline(currentStep || chief.currentAction),
    supportingText: currentStep
      ? `当前阶段：${currentStep}`
      : '审图内核持续派发任务，副审实时回流状态与技能动作。',
    providerLabel,
    progress,
    startedAt: auditStatus?.started_at,
    chief,
    finalReview,
    organizer,
    workerWall: {
      active: activeCards,
      recentCompleted: recentCompletedCards,
    },
    debugTimeline: {
      enabled: events.length > 0,
      events,
    },
    pill: {
      label: `${chief.title}调度中 ${Math.round(progress)}%`,
      issueCount: chief.issueCount,
      progress,
    },
  };
}

export function useAuditProgressViewModel(input: BuildAuditProgressViewModelInput) {
  return useMemo(
    () => buildAuditProgressViewModel(input),
    [input.auditStatus, input.events, input.providerLabel],
  );
}
