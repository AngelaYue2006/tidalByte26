// Role → viewer_id for fetches and SSE. Persisted in the URL as ?viewer_id=.

export type Role = "owner" | "contact";

export type Viewer = {
  role: Role;
  viewerId: string;
  label: string;
  name: string;
};

/** Demo viewers: Mary (owner) and Sarah (contact). */
export const VIEWERS: Record<Role, Viewer> = {
  owner: {
    role: "owner",
    viewerId: "mary",
    label: "Owner · Mary",
    name: "Mary Johnson",
  },
  contact: {
    role: "contact",
    viewerId: "sarah",
    label: "Contact · Sarah",
    name: "Sarah (daughter)",
  },
};

export const DEFAULT_ROLE: Role = "owner";
export const VIEWER_QUERY = "viewer_id";

export function roleFromViewerId(viewerId: string | null | undefined): Role {
  if (!viewerId) return DEFAULT_ROLE;
  const match = (Object.values(VIEWERS) as Viewer[]).find(
    (v) => v.viewerId === viewerId || v.role === viewerId,
  );
  return match?.role ?? DEFAULT_ROLE;
}

export function viewerFromRole(role: Role): Viewer {
  return VIEWERS[role];
}

export function viewerFromSearchParams(
  params: URLSearchParams | { get(name: string): string | null },
): Viewer {
  return viewerFromRole(roleFromViewerId(params.get(VIEWER_QUERY)));
}

/** Keep other query keys; set or replace viewer_id. */
export function hrefWithViewer(pathname: string, search: string, viewerId: string): string {
  const params = new URLSearchParams(search);
  params.set(VIEWER_QUERY, viewerId);
  const q = params.toString();
  return q ? `${pathname}?${q}` : pathname;
}
