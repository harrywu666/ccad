import * as api from '@/api';
import type { AuditEvent, AuditEventsResponse } from '@/types/api';

export interface EventSourceLike {
  onopen: ((event: Event) => void) | null;
  onerror: ((event: Event) => void) | null;
  addEventListener(type: string, listener: (event: MessageEvent) => void): void;
  removeEventListener(type: string, listener: (event: MessageEvent) => void): void;
  close(): void;
}

interface AuditEventStreamControllerOptions {
  projectId: string;
  version: number;
  onEvents: (events: AuditEvent[]) => void;
  onError?: (message: string) => void;
  onTransportChange?: (transport: 'stream' | 'poll') => void;
  onLoadingChange?: (loading: boolean) => void;
  createEventSource?: (url: string) => EventSourceLike;
  pollEvents?: (params: { version: number; since_id?: number; limit?: number }) => Promise<AuditEventsResponse>;
  reconnectDelayMs?: number;
  pollIntervalMs?: number;
  maxReconnectAttempts?: number;
  maxEvents?: number;
  listenEventKinds?: string[];
}

const DEFAULT_MAX_EVENTS = 160;
const RAW_PROCESS_EVENT_KINDS = new Set(['model_stream_delta', 'provider_stream_delta']);
const DEFAULT_LISTEN_EVENT_KINDS = [
  'phase_event',
  'phase_started',
  'phase_progress',
  'phase_completed',
  'warning',
  'error',
  'heartbeat',
  'model_stream_delta',
  'provider_stream_delta',
  'runner_broadcast',
  'runner_turn_started',
  'runner_turn_deferred',
  'runner_turn_cancelled',
  'runner_session_failed',
  'output_validation_failed',
  'output_repair_started',
  'output_repair_succeeded',
  'raw_output_saved',
  'worker_assignment_completed',
  'final_review_decision',
  'result_upsert',
  'result_summary',
  'master_recovery_requested',
  'master_recovery_succeeded',
  'master_recovery_exhausted',
  'master_handoff',
];

export const mergeAuditEvents = (
  current: AuditEvent[],
  incoming: AuditEvent[],
  maxItems = DEFAULT_MAX_EVENTS,
) => {
  const seen = new Set<number>();
  const merged = [...current, ...incoming]
    .filter((item) => {
      if (seen.has(item.id)) return false;
      seen.add(item.id);
      return true;
    })
    .sort((a, b) => a.id - b.id);

  if (merged.length <= maxItems) {
    return merged;
  }

  const summaryBudget = Math.max(1, Math.min(40, Math.floor(maxItems * 0.4)));
  const modelBudget = Math.max(1, Math.min(40, maxItems - summaryBudget));
  const summaryEvents = merged.filter((item) => !RAW_PROCESS_EVENT_KINDS.has(item.event_kind || ''));
  const modelEvents = merged.filter((item) => RAW_PROCESS_EVENT_KINDS.has(item.event_kind || ''));
  const preserved = [
    ...summaryEvents.slice(-summaryBudget),
    ...modelEvents.slice(-modelBudget),
  ].sort((a, b) => a.id - b.id);

  return preserved.slice(-maxItems);
};

const parseEventData = (raw: string): AuditEvent | null => {
  try {
    return JSON.parse(raw) as AuditEvent;
  } catch {
    return null;
  }
};

const buildStreamUrl = (projectId: string, version: number, sinceId?: number | null) => {
  const url = new URL(api.getAuditEventsStreamUrl(projectId), window.location.origin);
  url.searchParams.set('version', String(version));
  if (sinceId && sinceId > 0) {
    url.searchParams.set('since_id', String(sinceId));
  }
  return url.toString();
};

export function createAuditEventStreamController(options: AuditEventStreamControllerOptions) {
  let events: AuditEvent[] = [];
  let lastEventId = 0;
  let reconnectAttempts = 0;
  let stopped = false;
  let currentSource: EventSourceLike | null = null;
  let reconnectTimer: number | null = null;
  let pollTimer: number | null = null;

  const createSource = options.createEventSource ?? ((url: string) => new EventSource(url));
  const pollEvents = options.pollEvents ?? ((params) => api.getAuditEvents(options.projectId, params));
  const reconnectDelayMs = options.reconnectDelayMs ?? 1500;
  const pollIntervalMs = options.pollIntervalMs ?? 2000;
  const maxReconnectAttempts = options.maxReconnectAttempts ?? 3;
  const maxEvents = options.maxEvents ?? DEFAULT_MAX_EVENTS;
  const listenEventKinds = Array.from(
    new Set((options.listenEventKinds && options.listenEventKinds.length > 0)
      ? options.listenEventKinds
      : DEFAULT_LISTEN_EVENT_KINDS),
  );

  const clearTimers = () => {
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
    if (pollTimer !== null) {
      window.clearTimeout(pollTimer);
      pollTimer = null;
    }
  };

  const emitEvents = (incoming: AuditEvent[]) => {
    if (!incoming.length) return;
    events = mergeAuditEvents(events, incoming, maxEvents);
    const newest = incoming[incoming.length - 1];
    lastEventId = Math.max(lastEventId, newest.id);
    options.onEvents(events);
  };

  const handleMessage = (event: MessageEvent) => {
    const payload = parseEventData(event.data);
    if (!payload) return;
    emitEvents([payload]);
    const eventId = Number(event.lastEventId || payload.id);
    if (Number.isFinite(eventId) && eventId > 0) {
      lastEventId = Math.max(lastEventId, eventId);
    }
  };

  const closeSource = () => {
    currentSource?.close();
    currentSource = null;
  };

  const startPolling = () => {
    options.onTransportChange?.('poll');
    options.onError?.('实时流暂时断开，已自动切换成普通刷新模式。');
    closeSource();

    const pollOnce = async () => {
      if (stopped) return;
      try {
        options.onLoadingChange?.(true);
        const response = await pollEvents({
          version: options.version,
          since_id: lastEventId || undefined,
          limit: 30,
        });
        if (stopped) return;
        emitEvents(response.items);
        if (response.next_since_id) {
          lastEventId = Math.max(lastEventId, response.next_since_id);
        }
      } catch {
        options.onError?.('普通刷新也暂时没拉到新日志，后台可能还在继续。');
      } finally {
        options.onLoadingChange?.(false);
        if (!stopped) {
          pollTimer = window.setTimeout(pollOnce, pollIntervalMs);
        }
      }
    };

    void pollOnce();
  };

  const connect = () => {
    if (stopped) return;
    clearTimers();
    closeSource();
    options.onTransportChange?.('stream');
    options.onLoadingChange?.(true);

    const source = createSource(buildStreamUrl(options.projectId, options.version, lastEventId || undefined));
    currentSource = source;

    listenEventKinds.forEach((type) => source.addEventListener(type, handleMessage));

    source.onopen = () => {
      reconnectAttempts = 0;
      options.onLoadingChange?.(false);
      options.onError?.('');
    };

    source.onerror = () => {
      closeSource();
      options.onLoadingChange?.(false);
      reconnectAttempts += 1;
      if (reconnectAttempts > maxReconnectAttempts) {
        startPolling();
        return;
      }
      options.onError?.(`实时流短暂断开，正在第 ${reconnectAttempts} 次自动重连。`);
      reconnectTimer = window.setTimeout(connect, reconnectDelayMs);
    };
  };

  return {
    start() {
      stopped = false;
      connect();
    },
    stop() {
      stopped = true;
      clearTimers();
      closeSource();
    },
    getLastEventId() {
      return lastEventId;
    },
  };
}
