import { describe, expect, it, vi } from 'vitest';
import type { AuditEvent, AuditEventsResponse } from '@/types/api';
import type { AuditResult } from '@/types';
import {
  createAuditResultStreamController,
  type EventSourceLike,
} from '../auditResultStream';

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

  emitError() {
    this.onerror?.(new Event('error'));
  }
}

const buildRow = (overrides: Partial<AuditResult> = {}): AuditResult => ({
  id: 'group_1',
  project_id: 'proj-1',
  audit_version: 1,
  type: 'index',
  severity: 'warning',
  sheet_no_a: 'G0.03',
  sheet_no_b: 'G0.04b',
  location: '索引A1',
  value_a: null,
  value_b: null,
  rule_id: null,
  finding_type: null,
  finding_status: 'confirmed',
  source_agent: 'index_review_agent',
  evidence_pack_id: null,
  review_round: 1,
  triggered_by: null,
  confidence: 0.9,
  description: '索引缺失',
  evidence_json: '{"anchors":[]}',
  locations: ['索引A1'],
  occurrence_count: 1,
  is_resolved: false,
  resolved_at: null,
  feedback_status: 'none',
  feedback_at: null,
  feedback_note: null,
  is_grouped: true,
  group_id: 'group_1',
  issue_ids: ['issue_1'],
  ...overrides,
});

const buildEvent = (overrides: Partial<AuditEvent> = {}): AuditEvent => ({
  id: 1,
  audit_version: 1,
  level: 'info',
  step_key: 'result_stream',
  agent_key: 'runner_agent',
  agent_name: 'Runner Agent',
  event_kind: 'result_upsert',
  progress_hint: null,
  message: 'Runner Agent 已向报告追加一条问题',
  created_at: '2026-03-11T10:00:00',
  meta: {
    delta_kind: 'upsert',
    view: 'grouped',
    row: buildRow(),
    counts: { total: 1, unresolved: { index: 1, dimension: 0, material: 0 } },
    source_issue_ids: ['issue_1'],
  },
  ...overrides,
});

describe('auditResultStream', () => {
  it('receives result_upsert and result_summary events', () => {
    const upserts: AuditResult[] = [];
    const rawRowsCount: number[] = [];
    const summaries: number[] = [];
    const controller = createAuditResultStreamController({
      projectId: 'proj-1',
      version: 3,
      createEventSource: (url) => new FakeEventSource(url),
      pollEvents: vi.fn<() => Promise<AuditEventsResponse>>(),
      onUpsert: ({ row, rawRows }) => {
        upserts.push(row);
        rawRowsCount.push(rawRows.length);
      },
      onSummary: ({ counts }) => summaries.push(counts?.total ?? 0),
    });

    controller.start();
    const source = FakeEventSource.instances.at(-1)!;
    source.emit(
      'result_upsert',
      buildEvent({
        id: 11,
        meta: {
          delta_kind: 'upsert',
          view: 'grouped',
          row: buildRow(),
          raw_rows: [buildRow({ id: 'issue_1', is_grouped: false, group_id: null, issue_ids: [] })],
          counts: { total: 1, unresolved: { index: 1, dimension: 0, material: 0 } },
          source_issue_ids: ['issue_1'],
        },
      }),
      '11',
    );
    source.emit(
      'result_summary',
      buildEvent({
        id: 12,
        event_kind: 'result_summary',
        meta: { delta_kind: 'summary', view: 'grouped', counts: { total: 2, unresolved: { index: 1, dimension: 1, material: 0 } } },
      }),
      '12',
    );

    expect(upserts).toHaveLength(1);
    expect(upserts[0].id).toBe('group_1');
    expect(rawRowsCount).toEqual([1]);
    expect(summaries).toEqual([2]);
    expect(controller.getLastEventId()).toBe(12);
  });

  it('reconnects with since_id after stream error', () => {
    vi.useFakeTimers();
    const controller = createAuditResultStreamController({
      projectId: 'proj-2',
      version: 5,
      createEventSource: (url) => new FakeEventSource(url),
      pollEvents: vi.fn<() => Promise<AuditEventsResponse>>(),
      onUpsert: vi.fn(),
      reconnectDelayMs: 100,
      maxReconnectAttempts: 2,
    });

    controller.start();
    const first = FakeEventSource.instances.at(-1)!;
    first.emit('result_upsert', buildEvent({ id: 22 }), '22');
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
      items: [buildEvent({ id: 31 })],
      next_since_id: 31,
    });
    const upserts: AuditResult[] = [];
    const controller = createAuditResultStreamController({
      projectId: 'proj-3',
      version: 2,
      createEventSource: (url) => new FakeEventSource(url),
      pollEvents,
      onUpsert: ({ row }) => upserts.push(row),
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
    expect(upserts.at(-1)?.id).toBe('group_1');
    vi.useRealTimers();
  });
});
