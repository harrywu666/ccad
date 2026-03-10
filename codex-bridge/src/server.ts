import { Codex, type Input, type Thread, type ThreadEvent } from "@openai/codex-sdk";
import { randomUUID } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  BRIDGE_REQUEST_OPS,
  type BridgeRequestEnvelope,
  type BridgeResponseEnvelope,
} from "./protocol.js";
import { SessionStore } from "./session-store.js";

type TurnPayload = {
  subsession_key?: string;
  thread_id?: string;
  input?: string;
  images?: string[];
};

const currentDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(currentDir, "..", "..");
const fakeMode = process.env.CODEX_BRIDGE_FAKE_MODE === "1";
const port = Number(process.env.CODEX_BRIDGE_PORT || 4318);
const store = new SessionStore();
const codex = fakeMode ? null : new Codex();

function json(
  response: ServerResponse,
  statusCode: number,
  payload: Record<string, unknown>,
) {
  response.writeHead(statusCode, { "content-type": "application/json; charset=utf-8" });
  response.end(`${JSON.stringify(payload)}\n`);
}

function writeNdjson(
  response: ServerResponse,
  requestId: string,
  type: BridgeResponseEnvelope["type"],
  payload: Record<string, unknown>,
) {
  const envelope: BridgeResponseEnvelope = {
    type,
    request_id: requestId,
    payload,
  };
  response.write(`${JSON.stringify(envelope)}\n`);
}

async function readJson<TPayload>(request: IncomingMessage): Promise<TPayload> {
  const chunks: Buffer[] = [];
  for await (const chunk of request) {
    chunks.push(Buffer.isBuffer(chunk) ? chunk : Buffer.from(chunk));
  }
  const text = Buffer.concat(chunks).toString("utf-8").trim();
  return text ? (JSON.parse(text) as TPayload) : ({} as TPayload);
}

function normalizeInput(payload: TurnPayload): Input {
  const text = String(payload.input || "").trim();
  const images = Array.isArray(payload.images) ? payload.images : [];
  if (images.length === 0) {
    return text;
  }
  return [
    { type: "text", text },
    ...images.map((path) => ({ type: "local_image" as const, path })),
  ];
}

function resolveThread(op: string, payload: TurnPayload): { thread: Thread; subsessionKey: string } {
  if (!codex) {
    throw new Error("Codex client is not available in fake mode");
  }
  const subsessionKey = String(payload.subsession_key || "").trim();
  if (!subsessionKey) {
    throw new Error("payload.subsession_key is required");
  }
  const record = store.getOrCreate(subsessionKey);
  if (op === "resume_turn") {
    const threadId = String(payload.thread_id || record.threadId || "").trim();
    if (!threadId) {
      throw new Error("resume_turn requires payload.thread_id or stored thread_id");
    }
    const thread = codex.resumeThread(threadId, {
      workingDirectory: repoRoot,
      skipGitRepoCheck: true,
    });
    store.attachThread(subsessionKey, thread, threadId);
    return { thread, subsessionKey };
  }
  if (record.thread) {
    return { thread: record.thread, subsessionKey };
  }
  if (record.threadId) {
    const thread = codex.resumeThread(record.threadId, {
      workingDirectory: repoRoot,
      skipGitRepoCheck: true,
    });
    store.attachThread(subsessionKey, thread, record.threadId);
    return { thread, subsessionKey };
  }
  const thread = codex.startThread({
    workingDirectory: repoRoot,
    skipGitRepoCheck: true,
  });
  store.attachThread(subsessionKey, thread);
  return { thread, subsessionKey };
}

function buildFakeThreadId(subsessionKey: string) {
  return `fake-thread:${subsessionKey}`;
}

async function streamFakeTurn(
  response: ServerResponse,
  requestId: string,
  payload: TurnPayload,
) {
  const subsessionKey = String(payload.subsession_key || "").trim();
  if (!subsessionKey) {
    throw new Error("payload.subsession_key is required");
  }
  const record = store.getOrCreate(subsessionKey);
  const threadId = record.threadId || buildFakeThreadId(subsessionKey);
  record.threadId = threadId;
  writeNdjson(response, requestId, "provider_stream_delta", {
    text: `fake:${String(payload.input || "").trim() || "ok"}`,
    thread_id: threadId,
    subsession_key: subsessionKey,
  });
  writeNdjson(response, requestId, "phase_event", {
    kind: "thread_ready",
    subsession_key: subsessionKey,
    thread_id: threadId,
  });
  writeNdjson(response, requestId, "done", {
    thread_id: threadId,
    subsession_key: subsessionKey,
    status: "ok",
  });
}

function extractAgentMessageText(event: ThreadEvent, previousText: string) {
  if (
    (event.type !== "item.updated" && event.type !== "item.completed") ||
    event.item.type !== "agent_message"
  ) {
    return { nextText: previousText, delta: "" };
  }
  const nextText = event.item.text || "";
  if (!nextText) {
    return { nextText: previousText, delta: "" };
  }
  if (nextText.startsWith(previousText)) {
    return { nextText, delta: nextText.slice(previousText.length) };
  }
  return { nextText, delta: nextText };
}

async function streamRealTurn(
  response: ServerResponse,
  requestId: string,
  op: string,
  payload: TurnPayload,
) {
  const { thread, subsessionKey } = resolveThread(op, payload);
  const controller = new AbortController();
  store.setAbortController(subsessionKey, controller);
  const record = store.getOrCreate(subsessionKey);
  let fullText = "";

  try {
    const { events } = await thread.runStreamed(normalizeInput(payload), {
      signal: controller.signal,
    });
    for await (const event of events) {
      if (event.type === "thread.started") {
        store.attachThread(subsessionKey, thread, event.thread_id);
        writeNdjson(response, requestId, "phase_event", {
          kind: "thread_started",
          thread_id: event.thread_id,
          subsession_key: subsessionKey,
        });
        continue;
      }
      if (event.type === "item.started" || event.type === "item.updated" || event.type === "item.completed") {
        if (event.item.type !== "agent_message") {
          writeNdjson(response, requestId, "phase_event", {
            kind: event.item.type,
            subsession_key: subsessionKey,
          });
        }
        const { nextText, delta } = extractAgentMessageText(event, fullText);
        fullText = nextText;
        if (delta) {
          writeNdjson(response, requestId, "provider_stream_delta", {
            text: delta,
            thread_id: thread.id || record.threadId,
            subsession_key: subsessionKey,
          });
        }
        continue;
      }
      if (event.type === "turn.failed" || event.type === "error") {
        const message = event.type === "error" ? event.message : event.error.message;
        writeNdjson(response, requestId, "error", {
          message,
          thread_id: thread.id || record.threadId,
          subsession_key: subsessionKey,
        });
        continue;
      }
      if (event.type === "turn.completed") {
        writeNdjson(response, requestId, "done", {
          status: "ok",
          usage: event.usage,
          output: fullText,
          thread_id: thread.id || record.threadId,
          subsession_key: subsessionKey,
        });
      }
    }
  } finally {
    store.clearAbortController(subsessionKey);
  }
}

async function handleTurn(
  request: IncomingMessage,
  response: ServerResponse,
) {
  const body = await readJson<BridgeRequestEnvelope<TurnPayload>>(request);
  const op = String(body.op || "").trim();
  if (!BRIDGE_REQUEST_OPS.includes(op as (typeof BRIDGE_REQUEST_OPS)[number])) {
    json(response, 400, { error: `unsupported op: ${op}` });
    return;
  }
  const requestId = String(body.request_id || randomUUID());

  if (op === "cancel_turn") {
    const subsessionKey = String(body.payload?.subsession_key || "").trim();
    if (!subsessionKey) {
      json(response, 400, { error: "payload.subsession_key is required" });
      return;
    }
    json(response, 200, {
      ok: store.cancelTurn(subsessionKey),
      request_id: requestId,
      subsession_key: subsessionKey,
    });
    return;
  }

  if (op === "close_thread") {
    const subsessionKey = String(body.payload?.subsession_key || "").trim();
    if (!subsessionKey) {
      json(response, 400, { error: "payload.subsession_key is required" });
      return;
    }
    json(response, 200, {
      ok: store.closeThread(subsessionKey),
      request_id: requestId,
      subsession_key: subsessionKey,
    });
    return;
  }

  response.writeHead(200, {
    "content-type": "application/x-ndjson; charset=utf-8",
    "cache-control": "no-cache",
  });

  try {
    if (fakeMode) {
      await streamFakeTurn(response, requestId, body.payload || {});
    } else {
      await streamRealTurn(response, requestId, op, body.payload || {});
    }
  } catch (error) {
    writeNdjson(response, requestId, "error", {
      message: error instanceof Error ? error.message : String(error),
    });
    writeNdjson(response, requestId, "done", {
      status: "failed",
    });
  } finally {
    response.end();
  }
}

const server = createServer(async (request, response) => {
  try {
    if (request.method === "GET" && request.url === "/health") {
      json(response, 200, {
        ok: true,
        fake_mode: fakeMode,
      });
      return;
    }
    if (request.method === "POST" && request.url === "/v1/bridge/turn") {
      await handleTurn(request, response);
      return;
    }
    json(response, 404, { error: "not found" });
  } catch (error) {
    json(response, 500, {
      error: error instanceof Error ? error.message : String(error),
    });
  }
});

server.listen(port, "127.0.0.1", () => {
  process.stdout.write(`codex bridge listening on ${port}\n`);
});
