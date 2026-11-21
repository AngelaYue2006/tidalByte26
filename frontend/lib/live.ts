// EventSource client for GET /api/live?viewer_id=... Applies snapshot, dedupes by id, reconnects.
// Poll fallback when NEXT_PUBLIC_LIVE_STREAM_MODE=poll. Full client lands in a later issue.

/** Same-origin SSE URL; viewer_id comes from the role picker. */
export function liveUrl(viewerId: string): string {
  return `/api/live?viewer_id=${encodeURIComponent(viewerId)}`;
}

export type LiveHandlers = {
  onEvent?: (data: unknown, id: string | null) => void;
  onError?: (err: Event) => void;
};

/**
 * Open the live stream for this viewer. Returns a close function.
 * Snapshot / dedupe / poll are implemented in the SSE client issue.
 */
export function connectLive(viewerId: string, handlers: LiveHandlers = {}): () => void {
  const mode = process.env.NEXT_PUBLIC_LIVE_STREAM_MODE ?? "sse";
  if (mode === "poll") {
    // Poll path is wired in the SSE client issue; keep the viewer_id contract here.
    return () => undefined;
  }

  const source = new EventSource(liveUrl(viewerId));
  source.onmessage = (ev) => {
    try {
      handlers.onEvent?.(JSON.parse(ev.data), ev.lastEventId || null);
    } catch {
      handlers.onEvent?.(ev.data, ev.lastEventId || null);
    }
  };
  source.onerror = (err) => {
    handlers.onError?.(err);
  };
  return () => source.close();
}
