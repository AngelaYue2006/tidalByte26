// Role-scoped dashboard projection. Contact never sees request.text or owner-only controls.

import type { DashboardState } from "@/lib/dashboard";
import type { Role } from "@/lib/viewer";

export type ProjectedDashboard = DashboardState & {
  /** Owner-only Approve UI. */
  canApprove: boolean;
  /** Contact-only ride reply UI. */
  canReplyRide: boolean;
};

/** Project live state for the current viewer role. */
export function projectForViewer(state: DashboardState, role: Role): ProjectedDashboard {
  const awaitingReply = !!state.contact?.message && !state.contact?.reply;
  const needsApproval = !!state.approval?.pick && !state.approval?.approved;

  if (role === "contact") {
    const request = state.request
      ? { chips: state.request.chips /* text omitted */ }
      : undefined;
    return {
      ...state,
      request,
      canApprove: false,
      canReplyRide: awaitingReply,
    };
  }

  return {
    ...state,
    canApprove: needsApproval,
    canReplyRide: false,
  };
}

/** True if projected request still carries raw text (must be false for contact). */
export function contactSeesRequestText(projected: ProjectedDashboard): boolean {
  return typeof projected.request?.text === "string" && projected.request.text.length > 0;
}
