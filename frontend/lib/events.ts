// TypeScript types for every dashboard event — checked against docs/ARCHITECTURE.md Live events
// and shared/events.schema.json (schema fills in as shared issues land).

export type EventVisibility = "owner" | "contact" | "internal";

export type CallStatus = "dialing" | "live" | "hold" | "done";
export type TranscriptSpeaker = "agent" | "clinic";
export type TransportStatus = "checking" | "unavailable" | "available";

/** Fields the backend's project_event adds on every persisted event. */
export type EventMeta = {
  visibility?: EventVisibility;
  task_id?: string;
  id?: number | string;
  at?: string;
  simulated?: boolean;
};

export type RequestEvent = {
  type: "request";
  text?: string;
  chips: string[];
} & EventMeta;

export type CallStartEvent = {
  type: "call_start";
  call_id: string;
  clinic: string;
  meta?: string;
} & EventMeta;

export type CallStatusEvent = {
  type: "call_status";
  call_id: string;
  status: CallStatus;
} & EventMeta;

export type TranscriptEvent = {
  type: "transcript";
  call_id: string;
  /** 1-based position in the call (live recorder / mock path). */
  seq?: number;
  speaker: TranscriptSpeaker;
  text: string;
} & EventMeta;

export type CallResultEvent = {
  type: "call_result";
  call_id: string;
  price: string;
  slot: string;
  insured: boolean;
  slotOk: boolean;
} & EventMeta;

export type DecisionEvent = {
  type: "decision";
  winner: string;
  title: string;
  reasons: string[];
  second: string[];
  tradeoff: string;
} & EventMeta;

export type BookedEvent = {
  type: "booked";
  calendar: string;
  sms_user: string;
  tentative?: boolean;
} & EventMeta;

export type NotifiedEvent = {
  type: "notified";
  sms_contact: string;
  sms_user?: string;
} & EventMeta;

export type ApprovalRequiredEvent = {
  type: "approval_required";
  pick: { clinic: string; slot: string; price: string };
  expires_at?: string;
} & EventMeta;

export type ApprovedEvent = {
  type: "approved";
  by: string;
  via: "dashboard" | "sms";
} & EventMeta;

export type TransportCheckEvent = {
  type: "transport_check";
  status: TransportStatus;
  reason?: string;
  simulated: true;
} & EventMeta;

export type ContactRequestEvent = {
  type: "contact_request";
  contact: string;
  message: string;
} & EventMeta;

export type ContactReplyEvent = {
  type: "contact_reply";
  contact: string;
  text: string;
  offer?: { can_drive?: boolean; pickup_time?: string };
} & EventMeta;

export type RideConfirmedEvent = {
  type: "ride_confirmed";
  driver: string;
  pickup_time: string;
} & EventMeta;

export type TaskUpdatedEvent = {
  type: "task_updated";
  status: string;
  /** Present on failed runs (NO_ELIGIBLE_OFFER, RANKING_FAILED, …). */
  reason?: string;
  message?: string;
} & EventMeta;

export type SnapshotEvent = {
  type: "snapshot";
  task?: { id?: string; status?: string; [key: string]: unknown };
  calls?: unknown[];
  events?: LiveEvent[];
  visibility?: EventVisibility;
};

export type HeartbeatEvent = {
  type: "heartbeat";
  visibility?: EventVisibility;
};

export type LiveEvent =
  | RequestEvent
  | CallStartEvent
  | CallStatusEvent
  | TranscriptEvent
  | CallResultEvent
  | DecisionEvent
  | BookedEvent
  | NotifiedEvent
  | ApprovalRequiredEvent
  | ApprovedEvent
  | TransportCheckEvent
  | ContactRequestEvent
  | ContactReplyEvent
  | RideConfirmedEvent
  | TaskUpdatedEvent
  | SnapshotEvent
  | HeartbeatEvent;

export function isLiveEvent(value: unknown): value is LiveEvent {
  return (
    typeof value === "object" &&
    value !== null &&
    "type" in value &&
    typeof (value as { type: unknown }).type === "string"
  );
}

/** task_id from a streamed or snapshot event, when present. */
export function eventTaskId(event: LiveEvent): string | undefined {
  if (event.type === "snapshot" || event.type === "heartbeat") return undefined;
  const id = (event as EventMeta).task_id;
  return typeof id === "string" && id.length > 0 ? id : undefined;
}
