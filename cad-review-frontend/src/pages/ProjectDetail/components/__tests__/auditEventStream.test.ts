import { describe, expect, it, vi } from 'vitest';
import type { AuditEvent, AuditEventsResponse } from '@/types/api';
import {
  createAuditEventStreamController,
  mergeAuditEvents,
  type EventSourceLike,
} from '../auditEventStream';

class FakeEventSource implements EventSourceLike {
  static instances: FakeEventSource[] = [];

  readonly url: string;
  onopen: ((event: Event) => void) | null = null;
  onerror: ((event: Event) => void) | null = null;
  private listeners = new Map<string, Set<(event: MessageEvent) => void>>();
  closed = false;

  constructor(url: string) {
    this.url = url;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type: string, listener: (event: MessageEvent) => void) {
    const listeners = this.listeners.get(type) ?? new Set();
    listeners.add(listener);
    this.listeners.set(type, listeners);
  }

  removeEventListener(type: string, listener: (event: MessageEvent) => void) {
    this.listeners.get(type)?.delete(listener);
  }

  close() {
    this.closed = true;
  }

  emit(type: string, payload: unknown, lastEventId = '') {
    const event = {
      data: JSON.stringify(payload),
      lastEventId,
    } as MessageEvent;
    const listeners = this.listeners.get(type);
    listeners?.forEach((listener) => listener(event));
  }

  emitOpen() {
    this.onopen?.(new Event('open'));
  }

  emitError() {
    this.onerror?.(new Event('error'));
  }
}

const buildEvent = (overrides: Partial<AuditEvent> = {}): AuditEvent => ({
  id: 1,
  audit_version: 1,
  level: 'info',
  step_key: 'task_planning',
  agent_key: 'master_planner_agent',
  agent_name: '总控规划Agent',
  event_kind: 'phase_event',
  progress_hint: 18,
  message: '正在规划',
  created_at: '2026-03-10T10:00:00',
  meta: {},
  ...overrides,
});

describe('auditEventStream', () => {
  it('receives sse events and appends them', () => {
    const received: AuditEvent[][] = [];
    const controller = createAuditEventStreamController({
      projectId: 'proj-1',
      version: 3,
      createEventSource: (url) => new FakeEventSource(url),
      pollEvents: vi.fn<() => Promise<AuditEventsResponse>>(),
      onEvents: (events) => received.push(events),
    });

    controller.start();
    const source = FakeEventSource.instances.at(-1)!;
    source.emit(
      'phase_event',
      buildEvent({ id: 11, message: '开始整理图纸', event_kind: 'phase_event' }),
      '11',
    );
    source.emit(
      'model_stream_delta',
      buildEvent({ id: 12, message: '先整理目录，再构建任务。', event_kind: 'model_stream_delta' }),
      '12',
    );

    expect(received.at(-1)).toEqual([
      expect.objectContaining({ id: 11, message: '开始整理图纸' }),
      expect.objectContaining({ id: 12, event_kind: 'model_stream_delta' }),
    ]);
    expect(controller.getLastEventId()).toBe(12);
  });

  it('reconnects with lastEventId after stream error', () => {
    vi.useFakeTimers();
    const controller = createAuditEventStreamController({
      projectId: 'proj-2',
      version: 8,
      createEventSource: (url) => new FakeEventSource(url),
      pollEvents: vi.fn<() => Promise<AuditEventsResponse>>(),
      onEvents: vi.fn(),
      reconnectDelayMs: 100,
      maxReconnectAttempts: 2,
    });

    controller.start();
    const first = FakeEventSource.instances.at(-1)!;
    first.emit(
      'phase_event',
      buildEvent({ id: 22, message: '第一条', event_kind: 'phase_event' }),
      '22',
    );
    first.emitError();

    vi.advanceTimersByTime(100);

    const second = FakeEventSource.instances.at(-1)!;
    expect(second).not.toBe(first);
    expect(second.url).toContain('since_id=22');
    expect(first.closed).toBe(true);
    vi.useRealTimers();
  });

  it('falls back to polling after repeated failures', async () => {
    vi.useFakeTimers();
    const pollEvents = vi.fn<() => Promise<AuditEventsResponse>>().mockResolvedValue({
      items: [buildEvent({ id: 31, message: '轮询补回事件' })],
      next_since_id: 31,
    });
    const received: AuditEvent[][] = [];
    const controller = createAuditEventStreamController({
      projectId: 'proj-3',
      version: 2,
      createEventSource: (url) => new FakeEventSource(url),
      pollEvents,
      onEvents: (events) => received.push(events),
      reconnectDelayMs: 50,
      pollIntervalMs: 50,
      maxReconnectAttempts: 2,
    });

    controller.start();
    FakeEventSource.instances.at(-1)!.emitError();
    vi.advanceTimersByTime(50);
    FakeEventSource.instances.at(-1)!.emitError();
    vi.advanceTimersByTime(50);
    FakeEventSource.instances.at(-1)!.emitError();
    vi.advanceTimersByTime(60);
    await Promise.resolve();

    expect(pollEvents).toHaveBeenCalled();
    expect(received.at(-1)?.[0]).toEqual(expect.objectContaining({ id: 31, message: '轮询补回事件' }));
    vi.useRealTimers();
  });

  it('merges duplicate events by id and keeps order', () => {
    const merged = mergeAuditEvents(
      [buildEvent({ id: 1, message: '旧事件' })],
      [
        buildEvent({ id: 1, message: '旧事件' }),
        buildEvent({ id: 2, message: '新事件' }),
      ],
      5,
    );

    expect(merged.map((item) => item.id)).toEqual([1, 2]);
    expect(merged[1].message).toBe('新事件');
  });

  it('keeps summary events even when model deltas dominate the tail', () => {
    const summaryEvents = Array.from({ length: 8 }, (_, index) =>
      buildEvent({
        id: index + 1,
        event_kind: 'phase_progress',
        message: `关键进展 ${index + 1}`,
      }),
    );
    const modelEvents = Array.from({ length: 20 }, (_, index) =>
      buildEvent({
        id: index + 101,
        event_kind: 'model_stream_delta',
        message: `模型碎片 ${index + 1}`,
      }),
    );

    const merged = mergeAuditEvents(summaryEvents, modelEvents, 10);

    expect(merged.some((item) => item.event_kind !== 'model_stream_delta')).toBe(true);
    expect(merged.some((item) => item.message === '关键进展 8')).toBe(true);
  });
});
