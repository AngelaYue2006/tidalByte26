// TypeScript types for every dashboard event — checked against docs/ARCHITECTURE.md Live events
// and shared/events.schema.json (schema fills in as shared issues land).

export type EventVisibility = "owner" | "contact" | "internal";

export type CallStatus = "dialing" | "live" | "hold" | "done";
export type TranscriptSpeaker = "agent" | "clinic";
export type TransportStatus = "checking" | "unavailable" | "available";

export type RequestEvent = {
  type: "request";
  text?: string;
  chips: string[];
  visibility?: EventVisibility;
};

export type CallStartEvent = {
  type: "call_start";
  call_id: string;
  clinic: string;
  meta?: string;
  visibility?: EventVisibility;
};

export type CallStatusEvent = {
  type: "call_status";
  call_id: string;
  status: CallStatus;
  visibility?: EventVisibility;
};

export type TranscriptEvent = {
  type: "transcript";
  call_id: string;
  speaker: TranscriptSpeaker;
  text: string;
  visibility?: EventVisibility;
};

export type CallResultEvent = {
  type: "call_result";
  call_id: string;
  price: string;
  slot: string;
  insured: boolean;
  slotOk: boolean;
  visibility?: EventVisibility;
};

export type DecisionEvent = {
  type: "decision";
  winner: string;
  title: string;
  reasons: string[];
  second: string[];
  tradeoff: string;
  visibility?: EventVisibility;
};

export type BookedEvent = {
  type: "booked";
  calendar: string;
  sms_user: string;
  tentative?: boolean;
  visibility?: EventVisibility;
};

export type NotifiedEvent = {
  type: "notified";
  sms_contact: string;
  sms_user?: string;
  visibility?: EventVisibility;
};

export type ApprovalRequiredEvent = {
  type: "approval_required";
  pick: { clinic: string; slot: string; price: string };
  expires_at?: string;
  visibility?: EventVisibility;
};

export type ApprovedEvent = {
  type: "approved";
  by: string;
  via: "dashboard" | "sms";
  visibility?: EventVisibility;
};

export type TransportCheckEvent = {
  type: "transport_check";
  status: TransportStatus;
  reason?: string;
  simulated: true;
  visibility?: EventVisibility;
};

export type ContactRequestEvent = {
  type: "contact_request";
  contact: string;
  message: string;
  visibility?: EventVisibility;
};

export type ContactReplyEvent = {
  type: "contact_reply";
  contact: string;
  text: string;
  offer?: { can_drive?: boolean; pickup_time?: string };
  visibility?: EventVisibility;
};

export type RideConfirmedEvent = {
  type: "ride_confirmed";
  driver: string;
  pickup_time: string;
  visibility?: EventVisibility;
};

export type TaskUpdatedEvent = {
  type: "task_updated";
  status: string;
  visibility?: EventVisibility;
};

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
