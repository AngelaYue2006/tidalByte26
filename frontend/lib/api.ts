// fetch wrappers: postRequest, approve, contactOffer, getTasks, getTask, getEvents.
// Every call carries viewer_id from the role picker (URL).

function withViewer(path: string, viewerId: string, extra?: Record<string, string>): string {
  const params = new URLSearchParams({ viewer_id: viewerId, ...extra });
  return `${path}?${params.toString()}`;
}

/** History list URL — viewer-scoped. */
export function tasksUrl(viewerId: string, limit = 20): string {
  return withViewer("/api/tasks", viewerId, { limit: String(limit), owner_id: viewerId });
}

/** Single task projection for the current viewer. */
export function taskUrl(taskId: string, viewerId: string): string {
  return withViewer(`/api/tasks/${encodeURIComponent(taskId)}`, viewerId);
}

/** Ordered events for a task, filtered by viewer visibility. */
export function taskEventsUrl(taskId: string, viewerId: string): string {
  return withViewer(`/api/tasks/${encodeURIComponent(taskId)}/events`, viewerId);
}

async function parseJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text().catch(() => "");
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

/** History list — viewer-scoped. Shape: Task[] or { tasks: Task[] }. */
export async function getTasks(viewerId: string, limit = 20): Promise<unknown> {
  return parseJson(await fetch(tasksUrl(viewerId, limit)));
}

/** Single task projection for the current viewer. */
export async function getTask(taskId: string, viewerId: string): Promise<unknown> {
  return parseJson(await fetch(taskUrl(taskId, viewerId)));
}

/** Ordered events for a task, filtered by viewer visibility. */
export async function getEvents(taskId: string, viewerId: string): Promise<unknown> {
  return parseJson(await fetch(taskEventsUrl(taskId, viewerId)));
}

export async function postRequest(
  viewerId: string,
  body: { owner_id: string; actor_id: string; text?: string; audio_b64?: string; idempotency_key: string },
): Promise<unknown> {
  const res = await fetch(`/api/requests?viewer_id=${encodeURIComponent(viewerId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJson(res);
}

export async function approve(
  taskId: string,
  viewerId: string,
  body: { actor_id: string; decision: "approve" | "reject"; idempotency_key: string },
): Promise<unknown> {
  const res = await fetch(
    `/api/tasks/${encodeURIComponent(taskId)}/approve?viewer_id=${encodeURIComponent(viewerId)}`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
  return parseJson(res);
}

export async function contactOffer(
  viewerId: string,
  body: {
    task_id: string;
    contact_id: string;
    offer: { can_drive: boolean; pickup_time?: string };
    idempotency_key: string;
  },
): Promise<unknown> {
  const res = await fetch(`/api/contacts/offers?viewer_id=${encodeURIComponent(viewerId)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return parseJson(res);
}
