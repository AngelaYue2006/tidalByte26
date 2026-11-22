import { describe, expect, it } from "vitest";
import { enrichRequestText, knownPreferences, missingFields } from "./demoIntake";

describe("guided dental demo", () => {
  it("asks only what the owner has not provided", () => {
    expect(missingFields(knownPreferences("I need a dental cleaning"))).toEqual(["budget","ride"]);
    expect(missingFields(knownPreferences("A cleaning under $95.50"))).toEqual(["ride"]);
    expect(knownPreferences("Under $150 and I need a ride")).toEqual({ budget: 150, ride: true });
  });
  it("accepts an explicit no maximum, zero and negative ride answers", () => {
    expect(missingFields(knownPreferences("No maximum, I don't need a ride"))).toEqual([]);
    expect(knownPreferences("Up to $0; I drive myself")).toEqual({ budget: 0, ride: false });
  });
  it("folds answered preferences back into the request text", () => {
    expect(enrichRequestText("I need a cleaning", { budget: 150, ride: true })).toBe(
      "I need a cleaning Under $150. I need a ride.",
    );
    expect(enrichRequestText("Cleaning please", { budget: null, ride: false })).toBe(
      "Cleaning please No budget limit. I have my own ride.",
    );
  });
});
