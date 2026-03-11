import { useMemo } from 'react';
import type { AuditStatus } from '@/types';
import type { AuditEvent } from '@/types/api';

export type AuditPipelineState = 'complete' | 'current' | 'pending';
export type AuditPhaseState = 'complete' | 'current' | 'pending';

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

const RAW_PROCESS_EVENT_KINDS = new Set(['model_stream_delta', 'provider_stream_delta']);

const PIPELINE_STEPS = [
  {
    stepKey: 'prepare',
    title: '数据准备',
    description: '校验三线匹配，整理基础数据',
    match: ['校验三线匹配'],
  },
  {
    stepKey: 'context',
    title: '上下文构建',
    description: '整理图纸上下文，准备后续审核任务',
    match: ['构建图纸上下文'],
  },
  {
    stepKey: 'relationship_discovery',
    title: '关系分析',
    description: '分析跨图关系，找出后续要重点核对的图纸关联',
    match: ['AI 分析图纸关系'],
  },
  {
    stepKey: 'task_planning',
    title: '任务规划',
    description: '规划索引、尺寸和材料三类检查任务',
    match: ['规划审核任务图', '从任务账本恢复总控现场'],
  },
  {
    stepKey: 'index',
    title: '索引核对',
    description: '检查断链、缺失和孤立索引',
    match: ['索引核对'],
  },
  {
    stepKey: 'dimension',
    title: '尺寸核对',
    description: '比对跨图尺寸是否一致',
    match: ['尺寸核对'],
  },
  {
    stepKey: 'material',
    title: '材料核对',
    description: '检查材料信息是否一致',
    match: ['材料核对'],
  },
];

const HEADLINE_FLOW = [
  { match: ['校验三线匹配'], title: '准备检查' },
  { match: ['构建图纸上下文'], title: '提取图纸信息' },
  { match: ['AI 分析图纸关系'], title: '分析跨图关系' },
  { match: ['规划审核任务图', '从任务账本恢复总控现场'], title: '预规划审核任务' },
  { match: ['索引核对'], title: '索引断链核对' },
  { match: ['尺寸核对'], title: '尺寸比对核查' },
  { match: ['材料核对'], title: '材料表验证' },
  { match: ['审核完成'], title: '生成报告' },
];

function clampProgress(progress?: number | null) {
  return Math.max(0, Math.min(100, progress || 0));
}

function parseIssueCount(event?: AuditEvent | null) {
  if (!event?.meta || typeof event.meta !== 'object') return null;
  const value = event.meta.issues;
  return typeof value === 'number' ? value : null;
}

function resolveHeadline(currentStep?: string | null) {
  if (!currentStep) return '正在审核中';
  const matched = HEADLINE_FLOW.find((item) => item.match.some((text) => currentStep.includes(text)));
  return matched ? matched.title : currentStep;
}

function getLatestSummaryEvent(events: AuditEvent[]) {
  const filtered = events.filter((event) => !RAW_PROCESS_EVENT_KINDS.has(event.event_kind || ''));
  return filtered[filtered.length - 1] ?? null;
}

function getActiveEvent(events: AuditEvent[]) {
  return [...events].reverse().find((event) => event.event_kind === 'runner_broadcast')
    ?? getLatestSummaryEvent(events);
}

function findCurrentPipelineIndex(currentStep: string, events: AuditEvent[]) {
  const statusIndex = PIPELINE_STEPS.findIndex((item) => item.match.some((text) => currentStep.includes(text)));
  if (statusIndex >= 0) return statusIndex;

  const latestStepKey = [...events]
    .reverse()
    .find((event) => event.step_key && !RAW_PROCESS_EVENT_KINDS.has(event.event_kind || ''))
    ?.step_key;

  if (latestStepKey) {
    const index = PIPELINE_STEPS.findIndex((item) => item.stepKey === latestStepKey);
    if (index >= 0) return index;
  }

  return -1;
}

function buildPipeline(currentStep: string, events: AuditEvent[]) {
  const completedCounts = new Map<string, number | null>();
  const currentIndex = findCurrentPipelineIndex(currentStep, events);

  events.forEach((event) => {
    if (event.event_kind !== 'phase_completed' || !event.step_key) return;
    completedCounts.set(event.step_key, parseIssueCount(event));
  });

  return PIPELINE_STEPS.map((item, index) => {
    const completed = completedCounts.has(item.stepKey) || (currentIndex >= 0 && index < currentIndex);
    return {
      stepKey: item.stepKey,
      title: item.title,
      description: item.description,
      state: completed ? 'complete' : (index === currentIndex ? 'current' : 'pending'),
      issueCount: completedCounts.get(item.stepKey) ?? null,
    } satisfies AuditPipelineItem;
  });
}

function buildLegacyPhases(currentStep: string, progress: number): AuditPhaseCardViewModel[] {
  const normalizedProgress = clampProgress(progress);

  const planningDone =
    normalizedProgress >= 18 ||
    currentStep.includes('构建图纸上下文') ||
    currentStep.includes('AI 分析图纸关系') ||
    currentStep.includes('规划审核任务图') ||
    currentStep.includes('索引核对') ||
    currentStep.includes('尺寸核对') ||
    currentStep.includes('材料核对') ||
    currentStep.includes('审核完成');
  const checkingDone = normalizedProgress >= 85 || currentStep.includes('审核完成');
  const inChecking =
    !checkingDone &&
    (normalizedProgress >= 18 ||
      currentStep.includes('索引核对') ||
      currentStep.includes('尺寸核对') ||
      currentStep.includes('材料核对'));

  return [
    {
      title: '准备数据',
      description: '核对三线关系，分析跨图引用，并预规划审核任务',
      state: planningDone ? 'complete' : 'current',
    },
    {
      title: '深度审核',
      description: '执行索引、尺寸、材料等规则检查',
      state: checkingDone ? 'complete' : (inChecking ? 'current' : 'pending'),
    },
    {
      title: '生成报告',
      description: '汇总问题并输出审核报告',
      state: checkingDone ? 'current' : 'pending',
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

  return {
    headline: resolveHeadline(currentStep),
    supportingText: currentStep ? `当前阶段：${currentStep}` : '系统正在后台持续扫描和核对图纸数据。',
    activeAgentName,
    activeAgentMessage,
    providerLabel,
    progress,
    startedAt: auditStatus?.started_at,
    totalIssues,
    pipeline: buildPipeline(currentStep, events),
    phases: buildLegacyPhases(currentStep, progress),
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
