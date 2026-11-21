import { describe, expect, it } from "vitest";
import {
  parseTasksPayload,
  projectTaskForViewer,
  rideStatus,
  sortNewestFirst,
  toListItem,
} from "@/lib/history";
import { SEEDED_TASKS } from "@/lib/history_fixtures";

describe("history helpers", () => {
  it("sorts seeded runs newest first", () => {
    const sorted = sortNewestFirst(SEEDED_TASKS);
    expect(sorted.map((t) => t.id)).toEqual(["task-seed-2", "task-seed-1"]);
  });

  it("maps list fields: date, chips, pick, price, outcome, ride", () => {
    const item = toListItem(SEEDED_TASKS[0]);
    expect(item.chips).toContain("Dental cleaning");
    expect(item.pick).toBe("Bright Smile Dental");
    expect(item.price).toBe("$95");
    expect(item.outcome.label).toBe("Completed");
    expect(item.ride.label).toBe("No accessible ride");
  });

  it("labels contact-driving rides", () => {
    expect(rideStatus(SEEDED_TASKS[1]).label).toBe("Contact driving");
  });

  it("strips request_text for contact viewers", () => {
    const projected = projectTaskForViewer(SEEDED_TASKS[0], "contact");
    expect(projected.request_text).toBeUndefined();
    expect(projected.chips.length).toBeGreaterThan(0);
  });

  it("parses { tasks: [] } and bare arrays", () => {
    expect(parseTasksPayload({ tasks: SEEDED_TASKS })).toHaveLength(2);
    expect(parseTasksPayload(SEEDED_TASKS)).toHaveLength(2);
    expect(parseTasksPayload(null)).toEqual([]);
  });
});
