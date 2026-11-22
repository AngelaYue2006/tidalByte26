// Live page density: simple (grandma) vs detailed. Sticky in ?density=.

import type { Role } from "@/lib/viewer";

export type Density = "simple" | "detailed";

export const DENSITY_QUERY = "density";

export function defaultDensityForRole(role: Role): Density {
  return role === "owner" ? "simple" : "detailed";
}

export function densityFromSearchParams(
  params: URLSearchParams | { get(name: string): string | null },
  role: Role,
): Density {
  const raw = params.get(DENSITY_QUERY);
  if (raw === "simple" || raw === "detailed") return raw;
  return defaultDensityForRole(role);
}

/** Keep other query keys; set density. */
export function hrefWithDensity(pathname: string, search: string, density: Density): string {
  const params = new URLSearchParams(search);
  params.set(DENSITY_QUERY, density);
  const q = params.toString();
  return q ? `${pathname}?${q}` : pathname;
}
