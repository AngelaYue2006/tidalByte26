import { describe, expect, it } from "vitest";
import {
  defaultDensityForRole,
  densityFromSearchParams,
  hrefWithDensity,
} from "@/lib/density";

describe("density helpers", () => {
  it("defaults owner to simple and contact to detailed", () => {
    expect(defaultDensityForRole("owner")).toBe("simple");
    expect(defaultDensityForRole("contact")).toBe("detailed");
  });

  it("reads density from the query, else role default", () => {
    expect(densityFromSearchParams(new URLSearchParams("density=detailed"), "owner")).toBe(
      "detailed",
    );
    expect(densityFromSearchParams(new URLSearchParams(""), "owner")).toBe("simple");
    expect(densityFromSearchParams(new URLSearchParams(""), "contact")).toBe("detailed");
  });

  it("preserves other query keys when setting density", () => {
    const href = hrefWithDensity("/", "viewer_id=mary&preview=1", "detailed");
    expect(href).toContain("viewer_id=mary");
    expect(href).toContain("preview=1");
    expect(href).toContain("density=detailed");
  });
});
