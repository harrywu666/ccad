import { describe, expect, it, vi } from 'vitest';
import type { FeedbackThread, FeedbackThreadMessage } from '@/types/api';
import {
  createFeedbackThreadStreamController,
  type FeedbackEventSourceLike,
} from '../feedbackThreadStream';

class FakeEventSource implements FeedbackEventSourceLike {
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
    const event = { data: JSON.stringify(payload), lastEventId } as MessageEvent;
    this.listeners.get(type)?.forEach((listener) => listener(event));
  }

  emitError() {
    this.onerror?.(new Event('error'));
  }
}

const buildThread = (overrides: Partial<FeedbackThread> = {}): FeedbackThread => ({
  id: 'thread-1',
  project_id: 'proj-1',
  audit_result_id: 'result-1',
  result_group_id: 'group_1',
  audit_version: 1,
  status: 'resolved_incorrect',
  learning_decision: 'record_only',
  agent_decision: 'resolved_incorrect',
  agent_confidence: 0.82,
  opened_by: 'user',
  source_agent: 'index_review_agent',
  rule_id: 'index_alias_rule',
  issue_type: 'index',
  summary: '这是别名误报',
  resolution_reason: null,
  escalation_reason: null,
  created_at: null,
  updated_at: null,
  closed_at: null,
  messages: [],
  ...overrides,
});

const buildMessage = (overrides: Partial<FeedbackThreadMessage> = {}): FeedbackThreadMessage => ({
  id: 'msg-1',
  thread_id: 'thread-1',
  role: 'agent',
  message_type: 'decision',
  content: '这是别名误报',
  structured_json: null,
  created_at: null,
  ...overrides,
});

describe('feedbackThreadStream', () => {
  it('receives feedback_thread_upsert events', () => {
    const threads: FeedbackThread[] = [];
    const controller = createFeedbackThreadStreamController({
      projectId: 'proj-1',
      version: 1,
      createEventSource: (url) => new FakeEventSource(url),
      onThreadUpsert: (thread) => threads.push(thread),
    });

    controller.start();
    const source = FakeEventSource.instances.at(-1)!;
    source.emit('feedback_thread_upsert', {
      id: 11,
      audit_version: 1,
      event_kind: 'feedback_thread_upsert',
      message: '误报反馈线程已更新',
      created_at: '2026-03-11T12:00:00',
      meta: { thread: buildThread() },
    }, '11');

    expect(threads).toHaveLength(1);
    expect(threads[0].id).toBe('thread-1');
    expect(controller.getLastEventId()).toBe(11);
  });

  it('reconnects with since_id after stream error', () => {
    vi.useFakeTimers();
    const controller = createFeedbackThreadStreamController({
      projectId: 'proj-2',
      version: 3,
      threadId: 'thread-2',
      createEventSource: (url) => new FakeEventSource(url),
      onThreadUpsert: vi.fn(),
      reconnectDelayMs: 100,
      maxReconnectAttempts: 2,
    });

    controller.start();
    const first = FakeEventSource.instances.at(-1)!;
    first.emit('feedback_thread_upsert', {
      id: 21,
      audit_version: 3,
      event_kind: 'feedback_thread_upsert',
      message: '误报反馈线程已更新',
      meta: { thread: buildThread({ id: 'thread-2', result_group_id: null }) },
    }, '21');
    first.emitError();

    vi.advanceTimersByTime(100);

    const second = FakeEventSource.instances.at(-1)!;
    expect(second).not.toBe(first);
    expect(second.url).toContain('since_id=21');
    expect(second.url).toContain('thread_id=thread-2');
    expect(first.closed).toBe(true);
    vi.useRealTimers();
  });

  it('receives feedback_message_created events', () => {
    const messages: FeedbackThreadMessage[] = [];
    const controller = createFeedbackThreadStreamController({
      projectId: 'proj-1',
      version: 1,
      threadId: 'thread-1',
      createEventSource: (url) => new FakeEventSource(url),
      onThreadUpsert: vi.fn(),
      onMessageCreated: (message) => messages.push(message),
    });

    controller.start();
    const source = FakeEventSource.instances.at(-1)!;
    source.emit('feedback_message_created', {
      id: 12,
      audit_version: 1,
      event_kind: 'feedback_message_created',
      message: '误报反馈消息已创建',
      meta: {
        thread_id: 'thread-1',
        message_item: buildMessage(),
      },
    }, '12');

    expect(messages).toHaveLength(1);
    expect(messages[0].id).toBe('msg-1');
    expect(controller.getLastEventId()).toBe(12);
  });
});
