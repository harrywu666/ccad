export const BRIDGE_REQUEST_OPS = [
  "start_turn",
  "stream_turn",
  "resume_turn",
  "cancel_turn",
  "close_thread",
] as const;

export const BRIDGE_RESPONSE_TYPES = [
  "provider_stream_delta",
  "phase_event",
  "error",
  "done",
] as const;

export type BridgeRequestOp = (typeof BRIDGE_REQUEST_OPS)[number];
export type BridgeResponseType = (typeof BRIDGE_RESPONSE_TYPES)[number];

export interface BridgeRequestEnvelope<TPayload = Record<string, unknown>> {
  op: BridgeRequestOp;
  requestId: string;
  payload: TPayload;
}

export interface BridgeResponseEnvelope<TPayload = Record<string, unknown>> {
  type: BridgeResponseType;
  requestId: string;
  payload: TPayload;
}
