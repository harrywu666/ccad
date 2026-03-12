import { useMemo } from 'react';
import type { AuditStatus } from '@/types';
import type { AuditEvent } from '@/types/api';

export type AuditPipelineState = 'complete' | 'current' | 'pending';
export type AuditPhaseState = 'complete' | 'current' | 'pending';
export type AuditWorkerTaskState = 'running' | 'completed' | 'blocked';

export interface AuditPipelineItem {
  stepKey: string;
  title: string;
  description: string;
  state: AuditPipelineState;
  issueCount: number | null;
}

export interface AuditPhaseCardViewModel {
  title: string;
  description: string;
  state: AuditPhaseState;
}

export interface AuditWorkerTaskCardViewModel {
  key: string;
  title: string;
  agentName: string;
  skillLabel: string;
  status: AuditWorkerTaskState;
  statusLabel: string;
  summary: string;
  updatedAt?: string | null;
}

export interface AuditChiefSummaryViewModel {
  currentAction: string;
  summary: string;
  bottleneck: string;
  hypothesisCount: number;
  plannedTaskCount: number;
  runningTaskCount: number;
  completedTaskCount: number;
  queuedTaskCount: number;
  blockedTaskCount: number;
}

export interface AuditResultLedgerViewModel {
  issueCount: number;
  runningTaskCount: number;
  completedTaskCount: number;
  queuedTaskCount: number;
  blockedTaskCount: number;
}

export interface AuditProgressViewModel {
  headline: string;
  supportingText: string;
  activeAgentName: string;
  activeAgentMessage: string;
  providerLabel?: string;
  progress: number;
  startedAt?: string | null;
  totalIssues: number;
  pipeline: AuditPipelineItem[];
  phases: AuditPhaseCardViewModel[];
  chief: AuditChiefSummaryViewModel;
  workerBoard: {
    running: AuditWorkerTaskCardViewModel[];
    completed: AuditWorkerTaskCardViewModel[];
    blocked: AuditWorkerTaskCardViewModel[];
    queuedCount: number;
  };
  resultLedger: AuditResultLedgerViewModel;
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

interface WorkerSessionSnapshot {
  key: string;
  title: string;
  agentName: string;
  skillLabel: string;
  status: AuditWorkerTaskState;
  statusLabel: string;
  summary: string;
  updatedAt?: string | null;
  eventId: number;
}

const RAW_PROCESS_EVENT_KINDS = new Set(['model_stream_delta', 'provider_stream_delta']);
const WORKER_SESSION_EVENT_KINDS = new Set([
  'runner_turn_started',
  'raw_output_saved',
  'output_validation_failed',
  'output_repair_started',
  'output_repair_succeeded',
  'runner_turn_deferred',
  'runner_session_failed',
  'runner_turn_cancelled',
]);

const PIPELINE_STEPS = [
  {
    stepKey: 'chief_prepare',
    title: '主审准备',
    description: '主审整理上下文、关系和怀疑卡，准备派工。',
    match: ['校验三线匹配', '构建图纸上下文', 'AI 分析图纸关系', '规划审核任务图', '从任务账本恢复总控现场', '主审规划副审任务'],
    eventSteps: ['prepare', 'context', 'relationship_discovery', 'task_planning'],
  },
  {
    stepKey: 'worker_execution',
    title: '副审执行',
    description: '副审 Skill 并发执行索引、尺寸、材料和归属核对。',
    match: ['主审派发副审任务', '索引核对', '尺寸核对', '材料核对'],
    eventSteps: ['index', 'dimension', 'material'],
  },
  {
    stepKey: 'chief_finalize',
    title: '主审收束',
    description: '主审吸收副审结果，处理冲突并生成最终结论。',
    match: ['主审汇总完成', '主审完成结果收束', '生成报告', '审核完成'],
    eventSteps: ['chief_review', 'done'],
  },
];

const HEADLINE_FLOW = [
  { match: ['校验三线匹配', '构建图纸上下文', 'AI 分析图纸关系'], title: '主审准备' },
  { match: ['规划审核任务图', '从任务账本恢复总控现场', '主审规划副审任务', '主审派发副审任务'], title: '主审派工' },
  { match: ['索引核对', '尺寸核对', '材料核对'], title: '副审执行' },
  { match: ['审核完成', '主审汇总完成', '主审完成结果收束', '生成报告'], title: '主审汇总' },
];

const WORKER_SKILL_LABELS: Record<string, string> = {
  index_reference: '索引引用 Skill',
  material_semantic_consistency: '材料语义一致性 Skill',
  node_host_binding: '节点归属 Skill',
  spatial_consistency: '空间一致性 Skill',
  elevation_consistency: '标高一致性 Skill',
};

function clampProgress(progress?: number | null) {
  return Math.max(0, Math.min(100, progress || 0));
}

function parseIssueCount(event?: AuditEvent | null) {
  const meta = asMeta(event?.meta);
  const value = meta.issues;
  return typeof value === 'number' ? value : null;
}

function resolveHeadline(currentStep?: string | null) {
  if (!currentStep) return '主审组织审图';
  const matched = HEADLINE_FLOW.find((item) => item.match.some((text) => currentStep.includes(text)));
  return matched ? matched.title : currentStep;
}

function asMeta(meta: unknown): Record<string, unknown> {
  if (!meta || typeof meta !== 'object' || Array.isArray(meta)) return {};
  return meta as Record<string, unknown>;
}

function asText(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function getLatestSummaryEvent(events: AuditEvent[]) {
  const filtered = events.filter((event) => !RAW_PROCESS_EVENT_KINDS.has(event.event_kind || ''));
  return filtered[filtered.length - 1] ?? null;
}

function getActiveEvent(events: AuditEvent[]) {
  return [...events].reverse().find((event) => event.event_kind === 'runner_broadcast')
    ?? getLatestSummaryEvent(events);
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
    || agentId === 'chief_review'
    || agentName.includes('主审')
    || message.startsWith('主审 Agent');
}

function isWorkerSessionEvent(event: AuditEvent) {
  if (!WORKER_SESSION_EVENT_KINDS.has(asText(event.event_kind))) return false;
  if (isChiefEvent(event)) return false;
  return true;
}

function parseCountFromMessage(events: AuditEvent[], pattern: RegExp) {
  for (const event of [...events].reverse()) {
    const match = pattern.exec(asText(event.message));
    if (match) return Number(match[1] || 0);
  }
  return 0;
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

function extractSessionFragment(event: AuditEvent) {
  const meta = asMeta(event.meta);
  const sessionKey = asText(meta.session_key);
  if (sessionKey) {
    if (sessionKey.startsWith('worker_skill:')) return sessionKey;
    const parts = sessionKey.split(':');
    if (parts.length > 3) return parts.slice(3).join(':');
    return sessionKey;
  }

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

function extractWorkTitle(event: AuditEvent, sessionFragment: string) {
  const meta = asMeta(event.meta);
  const sourceSheet = asText(meta.source_sheet_no) || asText(meta.candidate_source_sheet_no);
  const targetSheet = asText(meta.target_sheet_no) || asText(meta.candidate_target_sheet_no);
  const sheetNo = asText(meta.sheet_no);
  if (sourceSheet && targetSheet) return `${sourceSheet} ↔ ${targetSheet}`;
  if (sheetNo) return `图纸 ${sheetNo}`;

  if (sessionFragment.startsWith('worker_skill:')) {
    const [, , source, targets] = sessionFragment.split(':');
    if (source && targets && targets !== 'SELF') return `${source} ↔ ${targets.replaceAll('__', ' / ')}`;
    if (source) return `图纸 ${source}`;
  }

  if (sessionFragment.startsWith('sheet_semantic:')) {
    const value = sessionFragment.split(':')[1];
    return value ? `图纸 ${value}` : '单图语义';
  }
  if (sessionFragment.startsWith('pair_compare:')) {
    const [, a, b] = sessionFragment.split(':');
    return a && b ? `${a} ↔ ${b}` : '跨图尺寸';
  }
  if (sessionFragment.startsWith('candidate_review:')) {
    const value = sessionFragment.split(':')[1];
    return value ? `候选关系 ${value.slice(0, 8)}` : '候选关系复核';
  }

  const sheets = asText(event.message).match(/[A-Z]{1,2}\d{3,4}[A-Z]?/g) || [];
  if (sheets.length >= 2) return `${sheets[0]} ↔ ${sheets[1]}`;
  if (sheets.length === 1) return `图纸 ${sheets[0]}`;
  return '副审任务';
}

function resolveSkillLabel(event: AuditEvent) {
  const skillId = resolveSkillId(event);
  if (skillId && WORKER_SKILL_LABELS[skillId]) return WORKER_SKILL_LABELS[skillId];
  return '通用复核 Skill';
}

function buildWorkerSummary(event: AuditEvent, title: string) {
  const meta = asMeta(event.meta);
  const eventKind = asText(event.event_kind);
  const rawMessage = asText(event.message);
  const skillId = resolveSkillId(event);

  if (eventKind === 'raw_output_saved') return `${title} 已收束本轮输出，等待主审消化结果。`;
  if (eventKind === 'output_validation_failed') return `${title} 的输出结构还在整理。`;
  if (eventKind === 'output_repair_started') return `${title} 正在整理输出格式。`;
  if (eventKind === 'output_repair_succeeded') return `${title} 已整理成标准结果。`;
  if (eventKind === 'runner_turn_deferred') return `${title} 暂时挂起，等待重试。`;
  if (eventKind === 'runner_session_failed') return `${title} 本轮执行失败，等待重试。`;
  if (eventKind === 'runner_turn_cancelled') return `${title} 已被用户中断。`;

  if (skillId === 'elevation_consistency') return `${title} 正在抽取单图标高语义。`;
  if (skillId === 'spatial_consistency') return `${title} 正在比对跨图空间关系。`;
  if (skillId === 'node_host_binding') return `${title} 正在复核节点归属。`;
  if (skillId === 'index_reference') return `${title} 正在核对索引引用。`;
  if (skillId === 'material_semantic_consistency') return `${title} 正在核对材料语义。`;

  if (rawMessage && !rawMessage.includes('已通过 Runner 发起一次') && !rawMessage.includes('原始输出已保存')) {
    return rawMessage;
  }
  return `${title} 正在执行副审任务。`;
}

function buildWorkerBoard(events: AuditEvent[], plannedTaskCount: number) {
  const sessions = new Map<string, WorkerSessionSnapshot>();

  events.forEach((event) => {
    if (!isWorkerSessionEvent(event)) return;
    const key = extractSessionFragment(event);
    if (!key) return;
    const existing = sessions.get(key);
    const title = existing?.title || extractWorkTitle(event, key);
    const agentName = asText(event.agent_name) || existing?.agentName || '副审 Agent';
    const skillLabel = resolveSkillLabel(event) || existing?.skillLabel;
    const summary = buildWorkerSummary(event, title);
    const eventKind = asText(event.event_kind);

    let status: AuditWorkerTaskState = existing?.status || 'running';
    let statusLabel = existing?.statusLabel || '处理中';
    if (eventKind === 'raw_output_saved' || eventKind === 'output_repair_succeeded') {
      status = 'completed';
      statusLabel = '已收束';
    } else if (eventKind === 'runner_turn_deferred' || eventKind === 'runner_session_failed' || eventKind === 'runner_turn_cancelled') {
      status = 'blocked';
      statusLabel = '待处理';
    } else {
      status = 'running';
      statusLabel = '处理中';
    }

    sessions.set(key, {
      key,
      title,
      agentName,
      skillLabel,
      status,
      statusLabel,
      summary,
      updatedAt: event.created_at,
      eventId: event.id,
    });
  });

  const items = [...sessions.values()].sort((left, right) => right.eventId - left.eventId);
  const running = items.filter((item) => item.status === 'running');
  const completed = items.filter((item) => item.status === 'completed');
  const blocked = items.filter((item) => item.status === 'blocked');
  const observedCount = items.length;
  const queuedCount = Math.max(0, plannedTaskCount - observedCount);

  return {
    running,
    completed,
    blocked,
    queuedCount,
  };
}

function buildChiefSummary(
  currentStep: string,
  events: AuditEvent[],
  workerBoard: ReturnType<typeof buildWorkerBoard>,
) {
  const chiefEvents = events.filter((event) => !RAW_PROCESS_EVENT_KINDS.has(event.event_kind || '') && isChiefEvent(event));
  const latestChiefEvent = chiefEvents[chiefEvents.length - 1] ?? null;
  const hypothesisCount = parseCountFromMessage(chiefEvents, /生成\s*(\d+)\s*条待核对怀疑卡/);
  const plannedTaskCount = Math.max(
    parseCountFromMessage(chiefEvents, /生成\s*(\d+)\s*张副审任务卡/),
    workerBoard.running.length + workerBoard.completed.length + workerBoard.blocked.length,
  );

  const currentAction = latestChiefEvent?.message
    || (currentStep ? `主审正在推进：${currentStep}` : '主审正在整理图纸上下文并准备拆分副审任务。');

  const summaryParts: string[] = [];
  if (hypothesisCount > 0) summaryParts.push(`已形成 ${hypothesisCount} 条怀疑卡`);
  if (plannedTaskCount > 0) summaryParts.push(`已派出 ${plannedTaskCount} 张副审任务卡`);
  if (workerBoard.running.length > 0) summaryParts.push(`当前 ${workerBoard.running.length} 张处理中`);
  if (workerBoard.completed.length > 0) summaryParts.push(`已收束 ${workerBoard.completed.length} 张`);
  if (workerBoard.queuedCount > 0) summaryParts.push(`还有 ${workerBoard.queuedCount} 张待调度`);
  if (workerBoard.blocked.length > 0) summaryParts.push(`${workerBoard.blocked.length} 张待处理`);

  let bottleneck = '主审正在等待更多副审结果回流。';
  if (workerBoard.running[0]) {
    const current = workerBoard.running[0];
    bottleneck = `${current.agentName} 正在处理 ${current.title}，调用 ${current.skillLabel}。`;
  } else if (workerBoard.queuedCount > 0) {
    bottleneck = `还有 ${workerBoard.queuedCount} 张副审任务排队中，主审还在持续调度。`;
  } else if (plannedTaskCount > 0 && workerBoard.completed.length >= plannedTaskCount) {
    bottleneck = '副审已基本收束，等待主审汇总最终报告。';
  }

  return {
    currentAction,
    summary: summaryParts.length ? summaryParts.join('，') : '主审正在组织这轮审图，副审会按实际需要持续被调起。',
    bottleneck,
    hypothesisCount,
    plannedTaskCount,
    runningTaskCount: workerBoard.running.length,
    completedTaskCount: workerBoard.completed.length,
    queuedTaskCount: workerBoard.queuedCount,
    blockedTaskCount: workerBoard.blocked.length,
  };
}

function findCurrentPipelineIndex(currentStep: string, events: AuditEvent[]) {
  const statusIndex = PIPELINE_STEPS.findIndex((item) => item.match.some((text) => currentStep.includes(text)));
  if (statusIndex >= 0) return statusIndex;

  const latestStepKey = [...events]
    .reverse()
    .find((event) => event.step_key && !RAW_PROCESS_EVENT_KINDS.has(event.event_kind || ''))
    ?.step_key;

  if (latestStepKey) {
    const index = PIPELINE_STEPS.findIndex((item) => item.eventSteps.includes(latestStepKey));
    if (index >= 0) return index;
  }

  return -1;
}

function buildPipeline(currentStep: string, events: AuditEvent[]) {
  const completedCounts = new Map<string, number | null>();
  const currentIndex = findCurrentPipelineIndex(currentStep, events);

  events.forEach((event) => {
    if (event.event_kind !== 'phase_completed' || !event.step_key) return;
    PIPELINE_STEPS.forEach((item) => {
      if (item.eventSteps.includes(event.step_key || '')) {
        completedCounts.set(item.stepKey, parseIssueCount(event));
      }
    });
  });

  return PIPELINE_STEPS.map((item, index) => {
    const isCurrent = index === currentIndex;
    const completed = !isCurrent && (completedCounts.has(item.stepKey) || (currentIndex >= 0 && index < currentIndex));
    return {
      stepKey: item.stepKey,
      title: item.title,
      description: item.description,
      state: completed ? 'complete' : (isCurrent ? 'current' : 'pending'),
      issueCount: completedCounts.get(item.stepKey) ?? null,
    } satisfies AuditPipelineItem;
  });
}

function buildChiefWorkerPhases(currentStep: string, progress: number): AuditPhaseCardViewModel[] {
  const normalizedProgress = clampProgress(progress);
  const isFinalize = normalizedProgress >= 95 || currentStep.includes('主审完成结果收束') || currentStep.includes('主审汇总完成');
  const isWorkerExecution =
    !isFinalize &&
    (normalizedProgress >= 18 ||
      currentStep.includes('索引核对') ||
      currentStep.includes('尺寸核对') ||
      currentStep.includes('材料核对'));

  return [
    {
      title: '主审准备',
      description: '主审整理上下文并决定要派出的副审任务。',
      state: isWorkerExecution || isFinalize ? 'complete' : 'current',
    },
    {
      title: '副审执行',
      description: '副审 Skill 并发运行，结果持续回流主审。',
      state: isFinalize ? 'complete' : (isWorkerExecution ? 'current' : 'pending'),
    },
    {
      title: '主审汇总',
      description: '主审消化副审结果并生成最终审图结论。',
      state: isFinalize ? 'current' : 'pending',
    },
  ];
}

export function buildAuditProgressViewModel({
  auditStatus,
  events = [],
  providerLabel,
}: BuildAuditProgressViewModelInput): AuditProgressViewModel {
  const currentStep = auditStatus?.current_step || '';
  const progress = clampProgress(auditStatus?.progress);
  const activeEvent = getActiveEvent(events);
  const activeAgentName = activeEvent?.agent_name || resolveHeadline(currentStep);
  const activeAgentMessage = activeEvent?.message || (
    currentStep ? `当前阶段：${currentStep}` : '系统正在后台持续扫描和核对图纸数据。'
  );
  const totalIssues = auditStatus?.total_issues || 0;
  const workerBoard = buildWorkerBoard(events, 0);
  const chief = buildChiefSummary(currentStep, events, workerBoard);
  const normalizedWorkerBoard = {
    ...workerBoard,
    queuedCount: Math.max(0, chief.plannedTaskCount - (
      workerBoard.running.length + workerBoard.completed.length + workerBoard.blocked.length
    )),
  };

  return {
    headline: resolveHeadline(currentStep),
    supportingText: currentStep ? `当前阶段：${currentStep}` : '主审会持续分派副审任务，你看到的是这轮真实调度现场。',
    activeAgentName,
    activeAgentMessage,
    providerLabel,
    progress,
    startedAt: auditStatus?.started_at,
    totalIssues,
    pipeline: buildPipeline(currentStep, events),
    phases: buildChiefWorkerPhases(currentStep, progress),
    chief: {
      ...chief,
      queuedTaskCount: normalizedWorkerBoard.queuedCount,
    },
    workerBoard: normalizedWorkerBoard,
    resultLedger: {
      issueCount: totalIssues,
      runningTaskCount: normalizedWorkerBoard.running.length,
      completedTaskCount: normalizedWorkerBoard.completed.length,
      queuedTaskCount: normalizedWorkerBoard.queuedCount,
      blockedTaskCount: normalizedWorkerBoard.blocked.length,
    },
    pill: {
      label: `${activeAgentName} ${Math.round(progress)}%`,
      issueCount: totalIssues,
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
