import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { getEvents, getTask } from "@/lib/api";
import { apiFetch, bootstrapSession } from "@/lib/session";

type Call = { url: string; init?: RequestInit };

/** A fetch stub that answers by URL: the first read 401s until /api/session has been called. */
function coldBackend() {
  const calls: Call[] = [];
  let hasCookie = false;
  const fetchStub = vi.fn(async (input: string, init?: RequestInit) => {
    calls.push({ url: input, init });
    if (input === "/api/session") {
      hasCookie = true;
      return new Response(JSON.stringify({ ok: true }), { status: 200 });
    }
    if (!hasCookie) {
      return new Response("dashboard session required: GET /api/session first", { status: 401 });
    }
    return new Response(JSON.stringify({ events: [{ id: 1, type: "heartbeat" }] }), { status: 200 });
  });
  return { calls, fetchStub };
}

describe("apiFetch session boundary", () => {
  const original = globalThis.fetch;

  beforeEach(() => {
    vi.useRealTimers();
  });

  afterEach(() => {
    globalThis.fetch = original;
  });

  it("a cold read with no cookie fetches the session once and retries once", async () => {
    const { calls, fetchStub } = coldBackend();
    globalThis.fetch = fetchStub as unknown as typeof fetch;

    const payload = (await getEvents("t1", "mary")) as { events: unknown[] };

    expect(payload.events).toHaveLength(1);
    expect(calls.map((c) => c.url)).toEqual([
      "/api/tasks/t1/events?viewer_id=mary",
      "/api/session",
      "/api/tasks/t1/events?viewer_id=mary",
    ]);
    expect(calls.every((c) => c.init?.credentials === "same-origin")).toBe(true);
  });

  it("direct history entry: two parallel cold reads share one session fetch", async () => {
    const { calls, fetchStub } = coldBackend();
    globalThis.fetch = fetchStub as unknown as typeof fetch;

    await Promise.all([getTask("t1", "mary"), getEvents("t1", "mary")]);

    expect(calls.filter((c) => c.url === "/api/session")).toHaveLength(1);
    expect(calls).toHaveLength(5); // 2 cold reads, 1 session, 2 retries
  });

  it("a 401 that survives the bootstrap is thrown after exactly one retry", async () => {
    const fetchStub = vi.fn(async (input: string) =>
      input === "/api/session"
        ? new Response("{}", { status: 200 })
        : new Response("dashboard session required", { status: 401 }),
    );
    globalThis.fetch = fetchStub as unknown as typeof fetch;

    await expect(getEvents("t1", "mary")).rejects.toThrow("dashboard session required");
    expect(fetchStub).toHaveBeenCalledTimes(3);
  });

  it("non-401 failures do not touch the session", async () => {
    const fetchStub = vi.fn(async () => new Response("no", { status: 404 }));
    globalThis.fetch = fetchStub as unknown as typeof fetch;

    await expect(getTask("missing", "mary")).rejects.toThrow("no");
    expect(fetchStub).toHaveBeenCalledTimes(1);
  });

  it("a session fetch that fails does not throw by itself; the next read reports it", async () => {
    const fetchStub = vi.fn(async (input: string) => {
      if (input === "/api/session") throw new TypeError("network down");
      return new Response("ok", { status: 200 });
    });
    globalThis.fetch = fetchStub as unknown as typeof fetch;

    await expect(bootstrapSession()).resolves.toBeUndefined();
    expect((await apiFetch("/api/tasks/t1?viewer_id=mary")).status).toBe(200);
  });
});
