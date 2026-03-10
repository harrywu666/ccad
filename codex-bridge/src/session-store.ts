import type { Thread } from "@openai/codex-sdk";

export interface BridgeSessionRecord {
  subsessionKey: string;
  thread: Thread | null;
  threadId: string | null;
  currentAbortController: AbortController | null;
}

export class SessionStore {
  private readonly sessions = new Map<string, BridgeSessionRecord>();

  getOrCreate(subsessionKey: string): BridgeSessionRecord {
    const existing = this.sessions.get(subsessionKey);
    if (existing) {
      return existing;
    }
    const created: BridgeSessionRecord = {
      subsessionKey,
      thread: null,
      threadId: null,
      currentAbortController: null,
    };
    this.sessions.set(subsessionKey, created);
    return created;
  }

  attachThread(subsessionKey: string, thread: Thread, threadId?: string | null) {
    const record = this.getOrCreate(subsessionKey);
    record.thread = thread;
    record.threadId = threadId ?? thread.id ?? record.threadId;
    return record;
  }

  setAbortController(subsessionKey: string, controller: AbortController | null) {
    const record = this.getOrCreate(subsessionKey);
    record.currentAbortController = controller;
    return record;
  }

  clearAbortController(subsessionKey: string) {
    const record = this.getOrCreate(subsessionKey);
    record.currentAbortController = null;
    return record;
  }

  cancelTurn(subsessionKey: string) {
    const record = this.sessions.get(subsessionKey);
    if (!record?.currentAbortController) {
      return false;
    }
    record.currentAbortController.abort("cancel_turn");
    record.currentAbortController = null;
    return true;
  }

  closeThread(subsessionKey: string) {
    return this.sessions.delete(subsessionKey);
  }
}
