import * as api from '@/api';
import type { FeedbackThread, FeedbackThreadMessage } from '@/types/api';

export interface FeedbackEventSourceLike {
  onopen: ((event: Event) => void) | null;
  onerror: ((event: Event) => void) | null;
  addEventListener(type: string, listener: (event: MessageEvent) => void): void;
  removeEventListener(type: string, listener: (event: MessageEvent) => void): void;
  close(): void;
}

interface FeedbackThreadStreamControllerOptions {
  projectId: string;
  version: number;
  threadId?: string;
  onThreadUpsert: (thread: FeedbackThread) => void;
  onMessageCreated?: (message: FeedbackThreadMessage, meta?: { threadId?: string; auditResultId?: string; resultGroupId?: string | null }) => void;
  onError?: (message: string) => void;
  onTransportChange?: (transport: 'stream') => void;
  onLoadingChange?: (loading: boolean) => void;
  createEventSource?: (url: string) => FeedbackEventSourceLike;
  reconnectDelayMs?: number;
  maxReconnectAttempts?: number;
}

type FeedbackStreamEvent = {
  id: number;
  audit_version: number;
  event_kind: string;
  message: string;
  created_at?: string | null;
  meta?: {
    thread?: FeedbackThread;
    thread_id?: string;
    audit_result_id?: string;
    result_group_id?: string | null;
    message_item?: FeedbackThreadMessage;
  };
};

const buildStreamUrl = (projectId: string, version: number, sinceId?: number | null, threadId?: string) => {
  const url = new URL(api.getFeedbackThreadsStreamUrl(projectId), window.location.origin);
  url.searchParams.set('audit_version', String(version));
  if (sinceId && sinceId > 0) {
    url.searchParams.set('since_id', String(sinceId));
  }
  if (threadId) {
    url.searchParams.set('thread_id', threadId);
  }
  return url.toString();
};

const parseEventData = (raw: string): FeedbackStreamEvent | null => {
  try {
    return JSON.parse(raw) as FeedbackStreamEvent;
  } catch {
    return null;
  }
};

export function createFeedbackThreadStreamController(options: FeedbackThreadStreamControllerOptions) {
  let lastEventId = 0;
  let reconnectAttempts = 0;
  let stopped = false;
  let currentSource: FeedbackEventSourceLike | null = null;
  let reconnectTimer: number | null = null;

  const createSource = options.createEventSource ?? ((url: string) => new EventSource(url));
  const reconnectDelayMs = options.reconnectDelayMs ?? 1500;
  const maxReconnectAttempts = options.maxReconnectAttempts ?? 5;

  const clearReconnectTimer = () => {
    if (reconnectTimer !== null) {
      window.clearTimeout(reconnectTimer);
      reconnectTimer = null;
    }
  };

  const closeSource = () => {
    currentSource?.close();
    currentSource = null;
  };

  const handleMessage = (event: MessageEvent) => {
    const payload = parseEventData(event.data);
    if (!payload) return;
    if (payload.event_kind === 'feedback_thread_upsert' && payload.meta?.thread) {
      options.onThreadUpsert(payload.meta.thread);
    }
    if (payload.event_kind === 'feedback_message_created' && payload.meta?.message_item) {
      options.onMessageCreated?.(payload.meta.message_item, {
        threadId: payload.meta.thread_id,
        auditResultId: payload.meta.audit_result_id,
        resultGroupId: payload.meta.result_group_id,
      });
    }
    const eventId = Number(event.lastEventId || payload.id);
    if (Number.isFinite(eventId) && eventId > 0) {
      lastEventId = Math.max(lastEventId, eventId);
    }
  };

  const connect = () => {
    if (stopped) return;
    clearReconnectTimer();
    closeSource();
    options.onTransportChange?.('stream');
    options.onLoadingChange?.(true);

    const source = createSource(buildStreamUrl(options.projectId, options.version, lastEventId || undefined, options.threadId));
    currentSource = source;
    source.addEventListener('feedback_thread_upsert', handleMessage);
    source.addEventListener('feedback_message_created', handleMessage);

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
        options.onError?.('反馈实时流暂时断开，请稍后重试。');
        return;
      }
      options.onError?.(`反馈流短暂断开，正在第 ${reconnectAttempts} 次自动重连。`);
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
      clearReconnectTimer();
      closeSource();
    },
    getLastEventId() {
      return lastEventId;
    },
  };
}
