import { describe, expect, it } from "vitest";
import { workspaceMode } from "./workspace";
import { hrefWithViewer } from "./viewer";

describe("activity navigation", () => {
  it("preserves the data source across route, role and density changes", () => {
    for (const mode of ["demo", "live"]) {
      const url = hrefWithViewer("/history", `workspace=${mode}&density=detailed`, "sarah");
      const query = new URL(url, "http://localhost").searchParams;
      expect(workspaceMode(query)).toBe(mode);
      expect(query.get("viewer_id")).toBe("sarah");
      expect(query.has("preview")).toBe(false);
    }
  });
  it("defaults to live SSE and only opens a sample when the URL asks", () => {
    expect(workspaceMode(new URLSearchParams("viewer_id=sarah&density=detailed"))).toBe("live");
    expect(workspaceMode(new URLSearchParams("workspace=demo"))).toBe("demo");
    expect(workspaceMode(new URLSearchParams("preview=1"))).toBe("sample");
  });
});
