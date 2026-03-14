import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, Clock3, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { AuditEvent } from '@/types/api';

interface AuditEventListProps {
  events: AuditEvent[];
  loading?: boolean;
  error?: string;
}

interface DisplayEvent {
  id: number;
  level: AuditEvent['level'];
  eventKind: string;
  agentName: string;
  message: string;
  detailMessage?: string | null;
  createdAt?: string | null;
  progressHint?: number | null;
  repeatCount: number;
  mergeKey?: string | null;
}

const RAW_PROCESS_EVENT_KINDS = new Set(['model_stream_delta', 'provider_stream_delta']);

const levelStyleMap = {
  info: {
    icon: RefreshCw,
    iconClassName: 'text-sky-600',
    labelClassName: 'text-sky-600',
    lineClassName: 'text-foreground',
    dotClassName: 'text-sky-600',
    label: '处理中',
  },
  success: {
    icon: CheckCircle2,
    iconClassName: 'text-emerald-600',
    labelClassName: 'text-emerald-600',
    lineClassName: 'text-foreground',
    dotClassName: 'text-emerald-600',
    label: '已完成',
  },
  warning: {
    icon: Clock3,
    iconClassName: 'text-amber-600',
    labelClassName: 'text-amber-600',
    lineClassName: 'text-foreground',
    dotClassName: 'text-amber-600',
    label: '等待中',
  },
  error: {
    icon: AlertCircle,
    iconClassName: 'text-rose-600',
    labelClassName: 'text-rose-600',
    lineClassName: 'text-foreground',
    dotClassName: 'text-rose-600',
    label: '出错了',
  },
} as const;

const formatTime = (value?: string | null) => {
  if (!value) return '--:--:--';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '--:--:--';
  return new Intl.DateTimeFormat('zh-CN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  }).format(date);
};

const getAgentName = (event: AuditEvent) => event.agent_name || '审图系统';

const getAgentDisplayName = (agentName: string) => {
  const normalized = String(agentName || '').trim();
  if (!normalized) return '审图系统';
  return normalized.endsWith('Agent') ? normalized.slice(0, -5) : normalized;
};

const isRetryEvent = (event: AuditEvent) => {
  if (event.event_kind !== 'phase_event') return false;
  const message = String(event.message || '');
  return message.includes('次重试') || message.includes('自动重连');
};

const getMergeKey = (event: AuditEvent) => {
  const meta = event.meta || {};
  const groupIndex = typeof meta.group_index === 'number' ? meta.group_index : '';
  const candidateIndex = typeof meta.candidate_index === 'number' ? meta.candidate_index : '';
  const mode = typeof meta.mode === 'string' ? meta.mode : '';
  const sheetNo = typeof meta.sheet_no === 'string' ? meta.sheet_no : '';
  const sourceSheetNo = typeof meta.source_sheet_no === 'string' ? meta.source_sheet_no : '';
  const targetSheetNo = typeof meta.target_sheet_no === 'string' ? meta.target_sheet_no : '';
  const sourceCandidate = typeof meta.candidate_source_sheet_no === 'string' ? meta.candidate_source_sheet_no : '';
  const targetCandidate = typeof meta.candidate_target_sheet_no === 'string' ? meta.candidate_target_sheet_no : '';
  const reason = typeof meta.reason === 'string' ? meta.reason : '';

  if (event.event_kind === 'heartbeat') {
    return ['heartbeat', event.agent_key || '', event.step_key || '', groupIndex, candidateIndex, mode, sheetNo, sourceSheetNo, targetSheetNo, sourceCandidate, targetCandidate].join(':');
  }
  if (isRetryEvent(event)) {
    return ['retry', event.agent_key || '', event.step_key || '', mode, sheetNo, sourceSheetNo, targetSheetNo, sourceCandidate, targetCandidate, reason].join(':');
  }
  return null;
};

const getWorkUnitKey = (event: AuditEvent) => {
  const meta = event.meta || {};
  const groupIndex = typeof meta.group_index === 'number' ? meta.group_index : null;
  const candidateIndex = typeof meta.candidate_index === 'number' ? meta.candidate_index : null;
  const sheetNo = typeof meta.sheet_no === 'string' ? meta.sheet_no.trim() : '';
  const sourceSheetNo = typeof meta.source_sheet_no === 'string' ? meta.source_sheet_no.trim() : '';
  const targetSheetNo = typeof meta.target_sheet_no === 'string' ? meta.target_sheet_no.trim() : '';
  const sourceCandidate = typeof meta.candidate_source_sheet_no === 'string' ? meta.candidate_source_sheet_no.trim() : '';
  const targetCandidate = typeof meta.candidate_target_sheet_no === 'string' ? meta.candidate_target_sheet_no.trim() : '';
  const indexNo = typeof meta.index_no === 'string' ? meta.index_no.trim() : '';

  if (groupIndex !== null) return `group:${groupIndex}`;
  if (candidateIndex !== null) return `candidate:${candidateIndex}`;
  if (sourceSheetNo || targetSheetNo || sourceCandidate || targetCandidate) {
    return `pair:${sourceSheetNo || sourceCandidate}:${targetSheetNo || targetCandidate}:${indexNo}`;
  }
  if (sheetNo) return `sheet:${sheetNo}`;
  if (indexNo) return `index:${indexNo}`;
  return null;
};

const getParallelUnitLabel = (event: AuditEvent) => {
  const meta = event.meta || {};
  const hasGroup = typeof meta.group_index === 'number' || typeof meta.candidate_index === 'number';
  const hasPair = typeof meta.source_sheet_no === 'string'
    || typeof meta.target_sheet_no === 'string'
    || typeof meta.candidate_source_sheet_no === 'string'
    || typeof meta.candidate_target_sheet_no === 'string';
  const hasSheet = typeof meta.sheet_no === 'string' && meta.sheet_no.trim().length > 0;
  const hasIndex = typeof meta.index_no === 'string' && meta.index_no.trim().length > 0;
  const hasReviewCandidates = typeof meta.review_candidates === 'number';

  if (hasGroup || hasPair) return '组';
  if (hasSheet) return '张图纸';
  if (hasIndex || hasReviewCandidates) return '条';
  return '项';
};

const buildDisplayEvents = (events: AuditEvent[]): DisplayEvent[] => {
  return events.reduce<DisplayEvent[]>((acc, event) => {
    const mergeKey = getMergeKey(event);
    const last = acc[acc.length - 1];
    if (mergeKey && last && last.mergeKey === mergeKey) {
      last.repeatCount += 1;
      last.createdAt = event.created_at;
      last.message = event.message;
      last.progressHint = event.progress_hint;
      last.id = event.id;
      return acc;
    }

    acc.push({
      id: event.id,
      level: event.level,
      eventKind: event.event_kind || 'phase_progress',
      agentName: getAgentName(event),
      message: event.message,
      createdAt: event.created_at,
      progressHint: event.progress_hint,
      repeatCount: 1,
      mergeKey,
    });
    return acc;
  }, []);
};

const buildSummaryDisplayEvents = (events: AuditEvent[]): DisplayEvent[] => {
  const groupedEvents = new Map<string, AuditEvent[]>();

  events.forEach((event) => {
    const groupKey = `${event.agent_key || event.agent_name || 'system'}:${event.step_key || 'unknown'}`;
    const bucket = groupedEvents.get(groupKey);
    if (bucket) {
      bucket.push(event);
      return;
    }
    groupedEvents.set(groupKey, [event]);
  });

  const passiveEvents: AuditEvent[] = [];
  const activeSummaries: DisplayEvent[] = [];

  groupedEvents.forEach((group) => {
    const latestEvent = group[group.length - 1];
    const infoEvents = group.filter((event) => event.level === 'info');
    const nonInfoEvents = group.filter((event) => event.level !== 'info');
    passiveEvents.push(...nonInfoEvents);

    if (!infoEvents.length || latestEvent.level !== 'info') {
      return;
    }

    const latestInfoEvent = infoEvents[infoEvents.length - 1];
    const workUnits = new Set<string>();
    let parallelUnit = '项';

    infoEvents.forEach((event) => {
      const unitKey = getWorkUnitKey(event);
      if (unitKey) {
        workUnits.add(unitKey);
      }
      const inferredUnit = getParallelUnitLabel(event);
      if (parallelUnit === '项' && inferredUnit !== '项') {
        parallelUnit = inferredUnit;
      }
    });

    const parallelCount = workUnits.size;
    const agentLabel = getAgentDisplayName(getAgentName(latestInfoEvent));
    const mergedMessage = parallelCount > 1
      ? `${agentLabel}中，当前并行 ${parallelCount} ${parallelUnit}`
      : latestInfoEvent.message;

    activeSummaries.push({
      id: latestInfoEvent.id,
      level: latestInfoEvent.level,
      eventKind: 'summary_aggregate',
      agentName: getAgentName(latestInfoEvent),
      message: mergedMessage,
      detailMessage: parallelCount > 1 ? latestInfoEvent.message : null,
      createdAt: latestInfoEvent.created_at,
      progressHint: latestInfoEvent.progress_hint,
      repeatCount: 1,
      mergeKey: null,
    });
  });

  return [...buildDisplayEvents(passiveEvents), ...activeSummaries].sort((left, right) => left.id - right.id);
};

export default function AuditEventList({
  events,
  loading = false,
  error,
}: AuditEventListProps) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const [viewMode, setViewMode] = useState<'summary' | 'process'>('summary');

  const displayEvents = useMemo(() => {
    if (viewMode === 'process') {
      return buildDisplayEvents(events.filter((event) => RAW_PROCESS_EVENT_KINDS.has(event.event_kind || '')));
    }
    const filtered = events.filter((event) => !RAW_PROCESS_EVENT_KINDS.has(event.event_kind || ''));
    return buildSummaryDisplayEvents(filtered);
  }, [events, viewMode]);

  useEffect(() => {
    const list = listRef.current;
    if (!list || !shouldStickToBottomRef.current) return;
    if (typeof list.scrollTo === 'function') {
      list.scrollTo({ top: list.scrollHeight, behavior: 'auto' });
      return;
    }
    list.scrollTop = list.scrollHeight;
  }, [displayEvents]);

  const content = useMemo(() => {
    if (!displayEvents.length) {
      return (
        <div className="flex min-h-[280px] items-center justify-center px-6 text-center text-[13px] leading-7 text-muted-foreground">
          {viewMode === 'summary'
            ? '审图内核或副审一有关键动作，这里就会继续往下滚动。'
            : '这里展示原始模型流，用来查卡顿、重试和输出收束。'}
        </div>
      );
    }

    if (viewMode === 'summary') {
      return (
        <div className="space-y-3 p-4">
          {displayEvents.map((event) => {
            const style = levelStyleMap[event.level] || levelStyleMap.info;
            const Icon = style.icon;
            const repeatText = event.repeatCount > 1 ? `（连续提醒 ${event.repeatCount} 次）` : '';
            const progressText = typeof event.progressHint === 'number' ? `${Math.round(event.progressHint)}%` : '--';
            return (
              <div
                key={event.id}
                className={cn(
                  'border bg-white px-4 py-4 transition-colors',
                  event.eventKind === 'heartbeat' ? 'border-amber-200 bg-amber-50/50' : 'border-border hover:border-primary/30',
                )}
              >
                <div className="flex items-start gap-3">
                  <div className="mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center border border-border bg-secondary/40">
                    <Icon className={cn('size-4 shrink-0', style.iconClassName, event.level === 'info' ? 'animate-spin' : '')} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2 text-[11px] leading-5">
                      <span className="rounded-full border border-border bg-secondary/30 px-2.5 py-0.5 font-medium text-foreground">
                        {event.agentName}
                      </span>
                      <span className={cn('font-medium', style.labelClassName)}>{style.label}</span>
                      <span className="text-muted-foreground">{formatTime(event.createdAt)}</span>
                      <span className="text-muted-foreground">进度 {progressText}</span>
                      {isRetryEvent({
                        id: event.id,
                        audit_version: 0,
                        level: event.level,
                        message: event.message,
                        meta: {},
                        event_kind: event.eventKind,
                      }) ? <span className="text-muted-foreground">retry</span> : null}
                    </div>
                    <p className={cn('mt-2 whitespace-pre-wrap break-words text-[14px] leading-7', style.lineClassName)}>
                      {event.message}
                      {repeatText}
                    </p>
                    {event.detailMessage ? (
                      <p className="mt-2 whitespace-pre-wrap break-words border-l-2 border-border pl-3 text-[12px] leading-6 text-muted-foreground">
                        {event.detailMessage}
                      </p>
                    ) : null}
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      );
    }

    return (
      <div className="space-y-1 bg-[#050608] p-3 font-mono text-[12px]">
        {displayEvents.map((event) => {
          const style = levelStyleMap[event.level] || levelStyleMap.info;
          const Icon = style.icon;
          const repeatText = event.repeatCount > 1 ? `（连续提醒 ${event.repeatCount} 次）` : '';
          const progressText = typeof event.progressHint === 'number' ? `${Math.round(event.progressHint)}%` : '--';
          const prefix = event.eventKind === 'heartbeat' ? '...' : '›';
          return (
            <div
              key={event.id}
              className={cn(
                'border-l pl-3 pr-2 py-1.5 transition-colors',
                event.eventKind === 'heartbeat' ? 'border-zinc-700/70 bg-white/[0.02]' : 'border-zinc-800 bg-transparent hover:bg-white/[0.03]',
              )}
            >
              <div className="flex items-start gap-2">
                <div className="mt-[2px] flex items-center gap-2 shrink-0">
                  <span className={cn('text-[11px]', style.dotClassName)}>{prefix}</span>
                  <Icon className={cn('size-3.5 shrink-0', style.iconClassName, event.level === 'info' ? 'animate-spin' : '')} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-[11px] leading-5">
                    <span className="text-zinc-500">{formatTime(event.createdAt)}</span>
                    <span className={cn('tracking-[0.06em]', style.labelClassName)}>{style.label}</span>
                    <span className="text-zinc-400">{event.agentName}</span>
                    <span className="text-zinc-600">[{progressText}]</span>
                  </div>
                  <p className="mt-0.5 whitespace-pre-wrap break-words text-[13px] leading-6 text-zinc-100">
                    {event.message}
                    {repeatText}
                  </p>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    );
  }, [displayEvents]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden border border-border bg-white shadow-sm">
      <div className="border-b border-border px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="text-[15px] font-semibold text-foreground">
              {viewMode === 'summary' ? '现场动作流' : '原始模型流'}
            </h3>
            <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
              {viewMode === 'summary'
                ? '这里只保留人能看懂的动作播报：谁在干嘛、刚收束了什么、哪里还在等。'
                : '这里展示底层原始流，用来排查卡顿、重试和输出收束。'}
            </p>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="rounded-none border-border text-[12px] shadow-none hover:bg-secondary hover:shadow-none"
              onClick={() => setViewMode(viewMode === 'summary' ? 'process' : 'summary')}
            >
              {viewMode === 'summary' ? '查看原始流' : '返回动作流'}
            </Button>
            {loading ? <RefreshCw className="mt-0.5 size-4 animate-spin text-primary" /> : null}
          </div>
        </div>
        {error ? (
          <div className="mt-3 border border-amber-300 bg-amber-50 px-3 py-2 text-[11px] leading-5 text-amber-900">
            实时流暂时中断，系统会自动重连或退回普通刷新。
          </div>
        ) : null}
      </div>

      <div
        ref={listRef}
        data-testid="audit-event-scroll"
        className={cn(
          'min-h-0 flex-1 overflow-y-auto',
          viewMode === 'summary' ? 'bg-secondary/10' : 'bg-[#050608]',
        )}
        onScroll={(event) => {
          const node = event.currentTarget;
          const distanceFromBottom = node.scrollHeight - node.scrollTop - node.clientHeight;
          shouldStickToBottomRef.current = distanceFromBottom < 48;
        }}
      >
        {content}
      </div>
    </div>
  );
}
