// TypeScript types for every dashboard event, generated from or checked against shared/events.schema.json.
// Full union lands with the SSE client issue; scaffold only needs the shared shape.

export type EventVisibility = "owner" | "contact" | "internal";

export type DashboardEventBase = {
  type: string;
  visibility?: EventVisibility;
};
