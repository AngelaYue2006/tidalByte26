// Dashboard state + pure reducer over LiveEvent. No React, no network.

import type {
  ApprovedEvent,
  ApprovalRequiredEvent,
  BookedEvent,
  CallResultEvent,
  CallStartEvent,
  CallStatus,
  CallStatusEvent,
  ContactReplyEvent,
  ContactRequestEvent,
  DecisionEvent,
  LiveEvent,
  NotifiedEvent,
  RequestEvent,
  RideConfirmedEvent,
  SnapshotEvent,
  TranscriptEvent,
  TransportCheckEvent,
} from "@/lib/events";

export type CallState = {
  call_id: string;
  clinic: string;
  meta?: string;
  status: CallStatus;
  transcripts: { speaker: TranscriptEvent["speaker"]; text: string }[];
  result?: {
    price: string;
    slot: string;
    insured: boolean;
    slotOk: boolean;
  };
};

export type DashboardState = {
  taskId?: string;
  taskStatus?: string;
  request?: { text?: string; chips: string[] };
  calls: CallState[];
  decision?: {
    winner: string;
    title: string;
    reasons: string[];
    second: string[];
    tradeoff: string;
  };
  approval?: {
    pick: { clinic: string; slot: string; price: string };
    expires_at?: string;
    approved?: { by: string; via: "dashboard" | "sms" };
  };
  transport?: {
    status: TransportCheckEvent["status"];
    reason?: string;
    simulated: true;
  };
  contact?: {
    name?: string;
    message?: string;
    reply?: { text: string; offer?: ContactReplyEvent["offer"] };
  };
  confirmations?: {
    booked?: { calendar: string; sms_user: string; tentative?: boolean };
    notified?: { sms_contact: string; sms_user?: string };
    ride?: { driver: string; pickup_time: string };
  };
};

export function emptyDashboard(): DashboardState {
  return { calls: [] };
}

function upsertCall(calls: CallState[], call_id: string, patch: Partial<CallState>): CallState[] {
  const idx = calls.findIndex((c) => c.call_id === call_id);
  if (idx === -1) {
    return [
      ...calls,
      {
        call_id,
        clinic: patch.clinic ?? call_id,
        meta: patch.meta,
        status: patch.status ?? "dialing",
        transcripts: patch.transcripts ?? [],
        result: patch.result,
      },
    ];
  }
  const next = [...calls];
  next[idx] = { ...next[idx], ...patch };
  return next;
}

function reduceOne(state: DashboardState, event: LiveEvent): DashboardState {
  switch (event.type) {
    case "heartbeat":
      return state;

    case "snapshot":
      return applySnapshot(event);

    case "request": {
      const e = event as RequestEvent;
      return {
        ...state,
        request: { text: e.text, chips: e.chips ?? [] },
      };
    }

    case "call_start": {
      const e = event as CallStartEvent;
      return {
        ...state,
        calls: upsertCall(state.calls, e.call_id, {
          clinic: e.clinic,
          meta: e.meta,
          status: "dialing",
          transcripts: [],
        }),
      };
    }

    case "call_status": {
      const e = event as CallStatusEvent;
      return {
        ...state,
        calls: upsertCall(state.calls, e.call_id, { status: e.status }),
      };
    }

    case "transcript": {
      const e = event as TranscriptEvent;
      const existing = state.calls.find((c) => c.call_id === e.call_id);
      const transcripts = [...(existing?.transcripts ?? []), { speaker: e.speaker, text: e.text }];
      return {
        ...state,
        calls: upsertCall(state.calls, e.call_id, { transcripts }),
      };
    }

    case "call_result": {
      const e = event as CallResultEvent;
      return {
        ...state,
        calls: upsertCall(state.calls, e.call_id, {
          result: {
            price: e.price,
            slot: e.slot,
            insured: e.insured,
            slotOk: e.slotOk,
          },
        }),
      };
    }

    case "decision": {
      const e = event as DecisionEvent;
      return {
        ...state,
        decision: {
          winner: e.winner,
          title: e.title,
          reasons: e.reasons,
          second: e.second,
          tradeoff: e.tradeoff,
        },
      };
    }

    case "approval_required": {
      const e = event as ApprovalRequiredEvent;
      return {
        ...state,
        approval: { pick: e.pick, expires_at: e.expires_at },
      };
    }

    case "approved": {
      const e = event as ApprovedEvent;
      return {
        ...state,
        approval: {
          pick: state.approval?.pick ?? { clinic: "", slot: "", price: "" },
          expires_at: state.approval?.expires_at,
          approved: { by: e.by, via: e.via },
        },
      };
    }

    case "transport_check": {
      const e = event as TransportCheckEvent;
      return {
        ...state,
        transport: { status: e.status, reason: e.reason, simulated: true },
      };
    }

    case "contact_request": {
      const e = event as ContactRequestEvent;
      return {
        ...state,
        contact: {
          ...state.contact,
          name: e.contact,
          message: e.message,
        },
      };
    }

    case "contact_reply": {
      const e = event as ContactReplyEvent;
      return {
        ...state,
        contact: {
          ...state.contact,
          name: e.contact,
          reply: { text: e.text, offer: e.offer },
        },
      };
    }

    case "ride_confirmed": {
      const e = event as RideConfirmedEvent;
      return {
        ...state,
        confirmations: {
          ...state.confirmations,
          ride: { driver: e.driver, pickup_time: e.pickup_time },
        },
      };
    }

    case "booked": {
      const e = event as BookedEvent;
      return {
        ...state,
        confirmations: {
          ...state.confirmations,
          booked: {
            calendar: e.calendar,
            sms_user: e.sms_user,
            tentative: e.tentative,
          },
        },
      };
    }

    case "notified": {
      const e = event as NotifiedEvent;
      return {
        ...state,
        confirmations: {
          ...state.confirmations,
          notified: { sms_contact: e.sms_contact, sms_user: e.sms_user },
        },
      };
    }

    case "task_updated":
      return { ...state, taskStatus: event.status };

    default:
      return state;
  }
}

/** Replace state from a snapshot (reconnect). Replays nested events when present. */
export function applySnapshot(snapshot: SnapshotEvent): DashboardState {
  let state = emptyDashboard();
  const task = snapshot.task;
  if (task && typeof task === "object") {
    if (typeof task.id === "string") state = { ...state, taskId: task.id };
    if (typeof task.status === "string") state = { ...state, taskStatus: task.status };
  }
  for (const ev of snapshot.events ?? []) {
    state = reduceOne(state, ev);
  }
  return state;
}

/** Pure reducer. `snapshot` replaces; `heartbeat` is a no-op. */
export function reduceDashboard(state: DashboardState, event: LiveEvent): DashboardState {
  return reduceOne(state, event);
}

/** Fold a list of events from empty state (tests and snapshot replay). */
export function foldEvents(events: LiveEvent[]): DashboardState {
  return events.reduce(reduceDashboard, emptyDashboard());
}
