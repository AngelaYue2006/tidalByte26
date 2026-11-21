// The shared dashboard session (docs/ARCHITECTURE.md, REST interface): every read route needs the
// lifeline_session cookie that GET /api/session issues. This is the one read boundary for the app:
// bootstrap the cookie once, and if a read still answers 401, bootstrap again and retry it once.

let inflight: Promise<void> | null = null;

/** Fetch the session cookie once. Parallel callers share one request; the browser keeps the cookie. */
export function bootstrapSession(): Promise<void> {
  if (!inflight) {
    inflight = fetch("/api/session", { credentials: "same-origin" })
      .then(() => undefined)
      .catch(() => undefined) // the read that follows surfaces the failure
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

/**
 * fetch for /api/* reads and posts. Sends the cookie, and on a 401 (no session yet: a cold visit to any
 * page, a dev backend restart) fetches the session once and retries the request once.
 */
export async function apiFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const withCookie: RequestInit = { credentials: "same-origin", ...init };
  const first = await fetch(input, withCookie);
  if (first.status !== 401) return first;
  await bootstrapSession();
  return fetch(input, withCookie);
}
