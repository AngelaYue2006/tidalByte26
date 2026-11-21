// EventSource client for GET /api/live?viewer_id=...
// Applies snapshot, dedupes by id, reconnects. Poll fallback when NEXT_PUBLIC_LIVE_STREAM_MODE=poll.

import { getEvents } from "@/lib/api";
import {
  emptyDashboard,
  reduceDashboard,
  type DashboardState,
} from "@/lib/dashboard";
import { isLiveEvent, type LiveEvent } from "@/lib/events";

export function liveUrl(viewerId: string): string {
  return `/api/live?viewer_id=${encodeURIComponent(viewerId)}`;
}

export type LiveHandlers = {
  onState?: (state: DashboardState) => void;
  onEvent?: (event: LiveEvent, id: string | null) => void;
  onError?: (err: unknown) => void;
};

export type ConnectLiveOptions = LiveHandlers & {
  /** Required when NEXT_PUBLIC_LIVE_STREAM_MODE=poll. */
  taskId?: string;
  /** Poll interval ms (default 1000). */
  pollMs?: number;
};

function streamMode(): "sse" | "poll" {
  const mode = process.env.NEXT_PUBLIC_LIVE_STREAM_MODE ?? "sse";
  return mode === "poll" ? "poll" : "sse";
}

function parsePayload(raw: string): unknown {
  try {
    return JSON.parse(raw) as unknown;
  } catch {
    return raw;
  }
}

type StreamGate = {
  state: DashboardState;
  seen: Set<string>;
  apply: (event: LiveEvent, id: string | null) => void;
};

function createGate(handlers: LiveHandlers): StreamGate {
  const gate: StreamGate = {
    state: emptyDashboard(),
    seen: new Set(),
    apply(event, id) {
      if (id !== null && id !== "" && gate.seen.has(id)) return;
      if (id) gate.seen.add(id);

      if (event.type === "snapshot") {
        // Reconnect: replace stream state; forget ids from the previous connection.
        gate.seen.clear();
        if (id) gate.seen.add(id);
        gate.state = reduceDashboard(emptyDashboard(), event);
      } else {
        gate.state = reduceDashboard(gate.state, event);
      }

      handlers.onEvent?.(event, id);
      handlers.onState?.(gate.state);
    },
  };
  return gate;
}

/** Fetch the dashboard session cookie once; the read routes require it. */
export async function bootstrapSession(): Promise<void> {
  try {
    await fetch("/api/session", { credentials: "same-origin" });
  } catch {
    // The stream or poll will surface the failure.
  }
}

function connectSse(viewerId: string, handlers: LiveHandlers): () => void {
  const gate = createGate(handlers);
  let source: EventSource | null = null;
  let closed = false;
  let gotMessage = false;
  let rebootstrapped = false;

  const open = () => {
    if (closed) return;
    source = new EventSource(liveUrl(viewerId));

    source.onmessage = (ev) => {
      gotMessage = true;
      const payload = parsePayload(ev.data);
      if (!isLiveEvent(payload)) return;
      gate.apply(payload, ev.lastEventId || null);
    };

    source.onerror = (err) => {
      if (!gotMessage && !rebootstrapped) {
        // First failure before any message: the session cookie was probably missing.
        rebootstrapped = true;
        source?.close();
        void bootstrapSession().then(open);
        return;
      }
      // Browser reconnects EventSource automatically; surface the error to the UI.
      handlers.onError?.(err);
    };
  };

  void bootstrapSession().then(open);

  return () => {
    closed = true;
    source?.close();
  };
}

function connectPoll(
  viewerId: string,
  taskId: string,
  handlers: LiveHandlers,
  pollMs: number,
): () => void {
  const gate = createGate(handlers);
  let stopped = false;
  let rebootstrapped = false;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const tick = async () => {
    if (stopped) return;
    timer = undefined;
    try {
      const payload = await getEvents(taskId, viewerId);
      for (const item of normalizeEventList(payload)) {
        gate.apply(item.event, item.id);
      }
    } catch (err) {
      const text = err instanceof Error ? err.message : String(err);
      if (!rebootstrapped && (text.includes("401") || text.includes("session required"))) {
        rebootstrapped = true;
        await bootstrapSession();
        if (!stopped) timer = setTimeout(() => void tick(), 0);
        return;
      }
      handlers.onError?.(err);
    } finally {
      if (!stopped && !timer) timer = setTimeout(() => void tick(), pollMs);
    }
  };

  void bootstrapSession().then(tick);

  return () => {
    stopped = true;
    if (timer) clearTimeout(timer);
  };
}

type Listed = { event: LiveEvent; id: string | null };

function normalizeEventList(payload: unknown): Listed[] {
  if (!Array.isArray(payload)) {
    if (payload && typeof payload === "object" && "events" in payload) {
      return normalizeEventList((payload as { events: unknown }).events);
    }
    return [];
  }
  const out: Listed[] = [];
  for (const row of payload) {
    if (!row || typeof row !== "object") continue;
    const rec = row as {
      id?: string | number;
      event?: unknown;
      payload?: unknown;
    };
    const id = rec.id === undefined || rec.id === null ? null : String(rec.id);
    const inner = rec.event ?? rec.payload ?? row;
    if (isLiveEvent(inner)) out.push({ event: inner, id });
  }
  return out;
}

/**
 * Open the live stream for this viewer. Returns a close function.
 * SSE reconnects via the browser; each reconnect snapshot replaces dashboard state.
 */
export function connectLive(viewerId: string, options: ConnectLiveOptions = {}): () => void {
  const { taskId, pollMs = 1000, ...handlers } = options;
  if (streamMode() === "poll") {
    if (!taskId) {
      handlers.onError?.(new Error("poll mode requires taskId"));
      return () => undefined;
    }
    return connectPoll(viewerId, taskId, handlers, pollMs);
  }
  return connectSse(viewerId, handlers);
}

export type { DashboardState };