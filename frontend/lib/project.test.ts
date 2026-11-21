import { describe, expect, it } from "vitest";
import { foldEvents } from "@/lib/dashboard";
import { LiveSession } from "@/lib/live";
import { contactSeesRequestText, projectForViewer } from "@/lib/project";
import { PROTOTYPE_SCENARIO } from "@/lib/scenario";
import type { LiveEvent } from "@/lib/events";

const withApproval: LiveEvent[] = [
  ...PROTOTYPE_SCENARIO,
  {
    type: "approval_required",
    pick: { clinic: "Bright Smile Dental", slot: "Thu 9:30", price: "$95" },
  },
  {
    type: "transport_check",
    status: "unavailable",
    reason: "None nearby",
    simulated: true,
  },
  {
    type: "contact_request",
    contact: "Sarah (daughter)",
    message: "Can you drive?",
  },
];

describe("projectForViewer", () => {
  const state = foldEvents(withApproval);

  it("strips request.text for contact and disables Approve", () => {
    const projected = projectForViewer(state, "contact");
    expect(contactSeesRequestText(projected)).toBe(false);
    expect(projected.request?.chips?.length).toBeGreaterThan(0);
    expect(projected.canApprove).toBe(false);
    expect(projected.canReplyRide).toBe(true);
    expect(projected.calls).toHaveLength(3);
    expect(projected.decision?.winner).toBe("a");
    expect(projected.transport?.simulated).toBe(true);
  });

  it("keeps request.text and Approve for owner", () => {
    const projected = projectForViewer(state, "owner");
    expect(projected.request?.text).toContain("dental cleaning");
    expect(projected.canApprove).toBe(true);
    expect(projected.canReplyRide).toBe(false);
  });
});

describe("LiveSession snapshot refresh (T11)", () => {
  it("restores from snapshot and ignores duplicate ids after reconnect", () => {
    const session = new LiveSession();
    session.push({ type: "request", chips: ["Dental cleaning"], text: "raw" }, "1");
    session.push(
      { type: "call_start", call_id: "a", clinic: "Bright Smile Dental", meta: "1.2 mi" },
      "2",
    );
    session.push({ type: "call_status", call_id: "a", status: "live" }, "3");
    expect(session.state.calls).toHaveLength(1);
    expect(session.state.calls[0].status).toBe("live");

    // Duplicate id ignored
    session.push({ type: "call_status", call_id: "a", status: "done" }, "3");
    expect(session.state.calls[0].status).toBe("live");

    // Refresh: snapshot replaces state
    session.push(
      {
        type: "snapshot",
        task: { id: "task-1", status: "calling" },
        events: [
          { type: "request", chips: ["Dental cleaning"] },
          { type: "call_start", call_id: "a", clinic: "Bright Smile Dental", meta: "1.2 mi" },
          { type: "call_status", call_id: "a", status: "hold" },
        ],
      },
      "100",
    );
    expect(session.state.taskId).toBe("task-1");
    expect(session.state.calls[0].status).toBe("hold");
    expect(session.state.request?.text).toBeUndefined();

    // Replaying pre-refresh ids must not double-apply after snapshot cleared seen set
    // but new connection would send snapshot first then only new events.
    // Same id "3" from old connection is not in seen; applying old event after snapshot would change state.
    // Server should not resend old ids after snapshot; client still dedupes within a connection:
    session.push({ type: "call_status", call_id: "a", status: "done" }, "101");
    expect(session.state.calls[0].status).toBe("done");
    session.push({ type: "call_status", call_id: "a", status: "live" }, "101");
    expect(session.state.calls[0].status).toBe("done");
  });
});
