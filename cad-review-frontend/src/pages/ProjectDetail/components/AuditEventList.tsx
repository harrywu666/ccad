import { useEffect, useMemo, useRef, useState } from 'react';
import { AlertCircle, CheckCircle2, Clock3, RefreshCw } from 'lucide-react';
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
  createdAt?: string | null;
  progressHint?: number | null;
  repeatCount: number;
  mergeKey?: string | null;
}

const RAW_PROCESS_EVENT_KINDS = new Set(['model_stream_delta', 'provider_stream_delta']);

const levelStyleMap = {
  info: {
    icon: RefreshCw,
    iconClassName: 'text-cyan-300',
    labelClassName: 'text-cyan-300',
    lineClassName: 'text-zinc-100',
    dotClassName: 'text-cyan-300',
    label: 'RUN',
  },
  success: {
    icon: CheckCircle2,
    iconClassName: 'text-emerald-300',
    labelClassName: 'text-emerald-300',
    lineClassName: 'text-zinc-100',
    dotClassName: 'text-emerald-300',
    label: 'DONE',
  },
  warning: {
    icon: Clock3,
    iconClassName: 'text-amber-300',
    labelClassName: 'text-amber-300',
    lineClassName: 'text-amber-100',
    dotClassName: 'text-amber-300',
    label: 'WAIT',
  },
  error: {
    icon: AlertCircle,
    iconClassName: 'text-rose-300',
    labelClassName: 'text-rose-300',
    lineClassName: 'text-rose-100',
    dotClassName: 'text-rose-300',
    label: 'ERR',
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

export default function AuditEventList({
  events,
  loading = false,
  error,
}: AuditEventListProps) {
  const listRef = useRef<HTMLDivElement | null>(null);
  const shouldStickToBottomRef = useRef(true);
  const [viewMode, setViewMode] = useState<'summary' | 'process'>('summary');

  const displayEvents = useMemo(() => {
    const hasRunnerBroadcast = events.some((event) => event.event_kind === 'runner_broadcast');
    const filtered = viewMode === 'summary'
      ? events.filter((event) => {
        if (RAW_PROCESS_EVENT_KINDS.has(event.event_kind || '')) return false;
        if (!hasRunnerBroadcast) return true;
        return event.event_kind === 'runner_broadcast' || event.level !== 'info';
      })
      : events.filter((event) => RAW_PROCESS_EVENT_KINDS.has(event.event_kind || ''));
    return buildDisplayEvents(filtered);
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
        <div className="flex min-h-[360px] items-center justify-center px-6 text-center font-mono text-[13px] leading-7 text-zinc-500">
          {viewMode === 'summary'
            ? '$ 审图启动后，这里会持续滚动输出 Runner 整理后的关键播报'
            : '$ 调试视图已就绪，这里显示 AI 引擎的原始流式片段'}
        </div>
      );
    }

    return (
      <div className="space-y-1 p-3 font-mono text-[12px]">
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
                    <span className={cn('uppercase tracking-[0.14em]', style.labelClassName)}>{style.label}</span>
                    <span className="text-zinc-400">{event.agentName}</span>
                    <span className="text-zinc-600">[{progressText}]</span>
                    {event.eventKind === 'heartbeat' ? (
                      <span className="text-zinc-600">heartbeat</span>
                    ) : null}
                    {isRetryEvent({
                      id: event.id,
                      audit_version: 0,
                      level: event.level,
                      message: event.message,
                      meta: {},
                      event_kind: event.eventKind,
                    }) ? (
                      <span className="text-zinc-600">retry</span>
                    ) : null}
                  </div>
                  <p className={cn('mt-0.5 whitespace-pre-wrap break-words text-[13px] leading-6', style.lineClassName)}>
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
    <div className="flex min-h-0 flex-col overflow-hidden border border-zinc-800 bg-[#07080b] shadow-2xl">
      <div className="border-b border-zinc-800 px-4 py-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h3 className="font-mono text-[15px] font-semibold text-zinc-100">terminal://audit-stream</h3>
            <p className="mt-1 text-[12px] leading-5 text-zinc-500">
              {viewMode === 'summary'
                ? '默认优先显示 Runner 整理后的播报，普通用户不直接看底层 JSON 碎片。'
                : '这里展示 AI 引擎的真实流式片段，方便调试它卡在哪、是否在重试。'}
            </p>
          </div>
          <div className="flex items-center gap-2">
            <div className="inline-flex overflow-hidden rounded-sm border border-zinc-800 bg-black/30 font-mono">
              <button
                type="button"
                className={cn(
                  'px-3 py-1.5 text-[11px] transition-colors',
                  viewMode === 'summary' ? 'bg-white/10 text-zinc-100' : 'text-zinc-500 hover:text-zinc-200',
                )}
                onClick={() => setViewMode('summary')}
              >
                stream
              </button>
              <button
                type="button"
                className={cn(
                  'border-l border-zinc-800 px-3 py-1.5 text-[11px] transition-colors',
                  viewMode === 'process' ? 'bg-white/10 text-zinc-100' : 'text-zinc-500 hover:text-zinc-200',
                )}
                onClick={() => setViewMode('process')}
              >
                model
              </button>
            </div>
            {loading ? <RefreshCw className="mt-0.5 size-4 animate-spin text-cyan-300" /> : null}
          </div>
        </div>
        {error ? (
          <div className="mt-3 border border-amber-500/30 bg-amber-500/10 px-3 py-2 font-mono text-[11px] leading-5 text-amber-200">
            [warn] 实时流暂时中断，系统会自动重连或退回普通刷新。
          </div>
        ) : null}
      </div>

      <div
        ref={listRef}
        data-testid="audit-event-scroll"
        className="min-h-0 flex-1 overflow-y-auto bg-[#050608]"
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
