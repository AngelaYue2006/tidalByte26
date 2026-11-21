// History list + detail helpers for GET /api/tasks and /api/tasks/{id}/events.

import type { LiveEvent } from "@/lib/events";

export type TaskStatus =
  | "intake"
  | "calendar"
  | "places"
  | "calling"
  | "ranking"
  | "awaiting_approval"
  | "booking"
  | "transport"
  | "awaiting_contact"
  | "completed"
  | "failed"
  | "cancelled";

export type HistoryTask = {
  id: string;
  owner_id: string;
  status: TaskStatus;
  viewer_role: "owner" | "contact";
  chips: string[];
  request_text?: string | null;
  booking: {
    clinic: string;
    slot_start: string;
    slot_end: string;
    price: string;
    status: "confirmed" | "tentative" | "rejected";
    confirmation_ref?: string | null;
  } | null;
  transport: {
    available: boolean;
    reason: string;
    simulated: boolean;
  } | null;
  decision: {
    winner_call_id?: string;
    reasons?: string[];
  } | null;
  created_at: string;
  updated_at: string;
};

export type HistoryListItem = {
  id: string;
  dateLabel: string;
  chips: string[];
  pick: string;
  price: string;
  outcome: { label: string; tone: "good" | "warn" | "bad" | "muted" };
  ride: { label: string; tone: "good" | "warn" | "bad" | "muted" };
};

const OUTCOME: Record<TaskStatus, HistoryListItem["outcome"]> = {
  completed: { label: "Completed", tone: "good" },
  failed: { label: "Failed", tone: "bad" },
  cancelled: { label: "Cancelled", tone: "muted" },
  awaiting_approval: { label: "Awaiting approval", tone: "warn" },
  awaiting_contact: { label: "Awaiting ride", tone: "warn" },
  booking: { label: "Booking", tone: "muted" },
  transport: { label: "Transport", tone: "muted" },
  calling: { label: "Calling", tone: "muted" },
  ranking: { label: "Ranking", tone: "muted" },
  intake: { label: "Intake", tone: "muted" },
  calendar: { label: "Calendar", tone: "muted" },
  places: { label: "Places", tone: "muted" },
};

export function parseTasksPayload(raw: unknown): HistoryTask[] {
  if (Array.isArray(raw)) return raw.filter(isHistoryTask);
  if (raw && typeof raw === "object" && Array.isArray((raw as { tasks?: unknown }).tasks)) {
    return ((raw as { tasks: unknown[] }).tasks).filter(isHistoryTask);
  }
  return [];
}

function isHistoryTask(value: unknown): value is HistoryTask {
  if (!value || typeof value !== "object") return false;
  const t = value as Record<string, unknown>;
  return typeof t.id === "string" && typeof t.status === "string" && typeof t.created_at === "string";
}

export function sortNewestFirst(tasks: HistoryTask[]): HistoryTask[] {
  return [...tasks].sort(
    (a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime(),
  );
}

export function formatTaskDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, {
    weekday: "short",
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

export function rideStatus(task: HistoryTask): HistoryListItem["ride"] {
  if (!task.transport) {
    if (task.status === "awaiting_contact") {
      return { label: "Waiting on contact", tone: "warn" };
    }
    return { label: "—", tone: "muted" };
  }
  if (task.transport.reason === "CONTACT_DRIVING") {
    return { label: "Contact driving", tone: "good" };
  }
  if (task.transport.available) {
    return { label: "Ride available", tone: "good" };
  }
  return { label: "No accessible ride", tone: "warn" };
}

export function toListItem(task: HistoryTask): HistoryListItem {
  return {
    id: task.id,
    dateLabel: formatTaskDate(task.created_at),
    chips: task.chips ?? [],
    pick: task.booking?.clinic ?? "—",
    price: task.booking?.price ?? "—",
    outcome: OUTCOME[task.status] ?? { label: task.status, tone: "muted" },
    ride: rideStatus(task),
  };
}

/** Strip owner-only request text for contact viewers. */
export function projectTaskForViewer(
  task: HistoryTask,
  role: "owner" | "contact",
): HistoryTask {
  if (role === "owner") return task;
  return { ...task, request_text: undefined };
}

export function parseEventsPayload(raw: unknown): LiveEvent[] {
  if (Array.isArray(raw)) return raw as LiveEvent[];
  if (raw && typeof raw === "object" && Array.isArray((raw as { events?: unknown }).events)) {
    return (raw as { events: LiveEvent[] }).events;
  }
  return [];
}

export function toneClass(tone: HistoryListItem["outcome"]["tone"]): string {
  if (tone === "good") return "chip chip-good";
  if (tone === "warn") return "chip chip-warn";
  if (tone === "bad") return "chip chip-bad";
  return "chip";
}
