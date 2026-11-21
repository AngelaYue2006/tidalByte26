import { describe, expect, it } from "vitest";
import {
  emptyDashboard,
  foldEvents,
  reduceDashboard,
} from "@/lib/dashboard";
import type { LiveEvent } from "@/lib/events";
import { PROTOTYPE_SCENARIO } from "@/lib/scenario";

describe("reduceDashboard with prototype SCENARIO", () => {
  it("folds the full scenario into request, three calls, decision and confirmations", () => {
    const state = foldEvents(PROTOTYPE_SCENARIO);

    expect(state.request?.chips).toEqual([
      "Dental cleaning",
      "Max $150",
      "Delta Dental",
      "Free: Tue pm, Thu am",
      "!Processed on device",
    ]);
    expect(state.request?.text).toContain("dental cleaning");

    expect(state.calls).toHaveLength(3);
    expect(state.calls.map((c) => c.call_id)).toEqual(["a", "b", "c"]);
    expect(state.calls.find((c) => c.call_id === "a")).toMatchObject({
      clinic: "Bright Smile Dental",
      status: "done",
      result: { price: "$95", slot: "Thu 9:30", insured: true, slotOk: true },
    });
    expect(state.calls.find((c) => c.call_id === "b")?.transcripts.length).toBeGreaterThan(0);
    expect(state.calls.find((c) => c.call_id === "c")?.result?.slotOk).toBe(false);

    expect(state.decision?.winner).toBe("a");
    expect(state.decision?.reasons).toHaveLength(3);
    expect(state.decision?.tradeoff).toContain("Smile Co.");

    expect(state.confirmations?.booked?.sms_user).toContain("Bright Smile");
    expect(state.confirmations?.notified?.sms_contact).toContain("Mary");
  });

  it("ignores heartbeat and replaces state on snapshot", () => {
    const mid = foldEvents(PROTOTYPE_SCENARIO.slice(0, 5));
    expect(mid.calls).toHaveLength(3);

    const afterBeat = reduceDashboard(mid, { type: "heartbeat" });
    expect(afterBeat).toEqual(mid);

    const snap: LiveEvent = {
      type: "snapshot",
      task: { id: "task-1", status: "calling" },
      events: [
        {
          type: "request",
          chips: ["Dental cleaning"],
        },
        { type: "call_start", call_id: "a", clinic: "Bright Smile Dental", meta: "1.2 mi" },
      ],
    };
    const afterSnap = reduceDashboard(mid, snap);
    expect(afterSnap.taskId).toBe("task-1");
    expect(afterSnap.taskStatus).toBe("calling");
    expect(afterSnap.calls).toHaveLength(1);
    expect(afterSnap.request?.chips).toEqual(["Dental cleaning"]);
    expect(afterSnap.decision).toBeUndefined();
  });

  it("starts from emptyDashboard", () => {
    expect(emptyDashboard()).toEqual({ calls: [] });
  });

  it("picks up task_id from streamed events so Approve works before a reconnect", () => {
    const state = foldEvents([
      {
        type: "task_updated",
        status: "intake",
        task_id: "task-live-1",
        id: 1,
      },
      {
        type: "request",
        text: "dental cleaning",
        chips: ["Dental cleaning"],
        task_id: "task-live-1",
        id: 2,
      },
      {
        type: "decision",
        winner: "task-live-1-a",
        title: "Why Nemotron picked Bright Smile Dental",
        reasons: ["Cheapest"],
        second: ["2nd closest"],
        tradeoff: "trade",
        task_id: "task-live-1",
        id: 3,
      },
      {
        type: "approval_required",
        pick: { clinic: "Bright Smile Dental", slot: "Thu 9:30", price: "$95" },
        task_id: "task-live-1",
        id: 4,
      },
    ]);
    expect(state.taskId).toBe("task-live-1");
    expect(state.request?.chips).toEqual(["Dental cleaning"]);
    expect(state.decision?.second).toEqual(["2nd closest"]);
    expect(state.approval?.pick.clinic).toBe("Bright Smile Dental");
  });

  it("tolerates a decision event missing second", () => {
    const state = foldEvents([
      {
        type: "decision",
        winner: "a",
        title: "Why Nemotron picked X",
        reasons: ["Fits"],
        // @ts-expect-error intentional incomplete live payload
        second: undefined,
        tradeoff: "trade",
        task_id: "t1",
      },
    ]);
    expect(state.decision?.second).toEqual([]);
    expect(state.taskId).toBe("t1");
  });
});
