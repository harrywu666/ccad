import * as api from '@/api';
import type { AuditResult } from '@/types';
import type { AuditEvent, AuditEventsResponse } from '@/types/api';

export interface EventSourceLike {
  onopen: ((event: Event) => void) | null;
  onerror: ((event: Event) => void) | null;
  addEventListener(type: string, listener: (event: MessageEvent) => void): void;
  removeEventListener(type: string, listener: (event: MessageEvent) => void): void;
  close(): void;
}

export interface AuditResultCounts {
  total: number;
  unresolved: {
    index: number;
    dimension: number;
    material: number;
  };
}

export interface AuditResultUpsertPayload {
  row: AuditResult;
  counts: AuditResultCounts | null;
  sourceIssueIds: string[];
}

export interface AuditResultSummaryPayload {
  counts: AuditResultCounts | null;
}

interface AuditResultStreamControllerOptions {
  projectId: string;
  version: number;
  onUpsert: (payload: AuditResultUpsertPayload) => void;
  onSummary?: (payload: AuditResultSummaryPayload) => void;
  onError?: (message: string) => void;
  onTransportChange?: (transport: 'stream' | 'poll') => void;
  onLoadingChange?: (loading: boolean) => void;
  createEventSource?: (url: string) => EventSourceLike;
  pollEvents?: (params: {
    version: number;
    since_id?: number;
    limit?: number;
    event_kinds?: string;
  }) => Promise<AuditEventsResponse>;
  reconnectDelayMs?: number;
  pollIntervalMs?: number;
  maxReconnectAttempts?: number;
}

const RESULT_EVENT_KINDS = new Set(['result_upsert', 'result_summary', 'heartbeat']);

const buildStreamUrl = (projectId: string, version: number, sinceId?: number | null) => {
  const url = new URL(api.getAuditResultsStreamUrl(projectId), window.location.origin);
  url.searchParams.set('version', String(version));
  if (sinceId && sinceId > 0) {
    url.searchParams.set('since_id', String(sinceId));
  }
  return url.toString();
};

const parseEventData = (raw: string): AuditEvent | null => {
  try {
    return JSON.parse(raw) as AuditEvent;
  } catch {
    return null;
  }
};

const parseCounts = (value: unknown): AuditResultCounts | null => {
  if (!value || typeof value !== 'object') return null;
  const raw = value as Record<string, unknown>;
  const unresolved = (raw.unresolved ?? null) as Record<string, unknown> | null;
  if (typeof raw.total !== 'number' || !unresolved) return null;
  return {
    total: raw.total,
    unresolved: {
      index: Number(unresolved.index ?? 0),
      dimension: Number(unresolved.dimension ?? 0),
      material: Number(unresolved.material ?? 0),
    },
  };
};

const parseUpsertPayload = (event: AuditEvent): AuditResultUpsertPayload | null => {
  if (event.event_kind !== 'result_upsert') return null;
  const meta = (event.meta ?? {}) as Record<string, unknown>;
  const row = meta.row as AuditResult | undefined;
  if (!row || typeof row !== 'object') return null;
  const sourceIssueIds = Array.isArray(meta.source_issue_ids)
    ? meta.source_issue_ids.map((item) => String(item))
    : [];
  return {
    row,
    counts: parseCounts(meta.counts),
    sourceIssueIds,
  };
};

const parseSummaryPayload = (event: AuditEvent): AuditResultSummaryPayload | null => {
  if (event.event_kind !== 'result_summary') return null;
  const meta = (event.meta ?? {}) as Record<string, unknown>;
  return { counts: parseCounts(meta.counts) };
};

export function createAuditResultStreamController(options: AuditResultStreamControllerOptions) {
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

  const handleEventPayload = (payload: AuditEvent) => {
    if (!RESULT_EVENT_KINDS.has(payload.event_kind || '')) return;
    if (payload.event_kind === 'result_upsert') {
      const upsert = parseUpsertPayload(payload);
      if (upsert) options.onUpsert(upsert);
      return;
    }
    if (payload.event_kind === 'result_summary') {
      const summary = parseSummaryPayload(payload);
      if (summary) options.onSummary?.(summary);
    }
  };

  const handleMessage = (event: MessageEvent) => {
    const payload = parseEventData(event.data);
    if (!payload) return;
    handleEventPayload(payload);
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
    options.onError?.('结果实时流暂时断开，已自动切换成普通刷新模式。');
    closeSource();

    const pollOnce = async () => {
      if (stopped) return;
      try {
        options.onLoadingChange?.(true);
        const response = await pollEvents({
          version: options.version,
          since_id: lastEventId || undefined,
          limit: 30,
          event_kinds: 'result_upsert,result_summary',
        });
        if (stopped) return;
        response.items.forEach(handleEventPayload);
        if (response.next_since_id) {
          lastEventId = Math.max(lastEventId, response.next_since_id);
        }
      } catch {
        options.onError?.('普通刷新也暂时没拉到新结果，后台可能还在继续。');
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

    ['result_upsert', 'result_summary', 'heartbeat'].forEach((type) => {
      source.addEventListener(type, handleMessage);
    });

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
      options.onError?.(`结果流短暂断开，正在第 ${reconnectAttempts} 次自动重连。`);
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

