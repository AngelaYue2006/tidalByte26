/** Only explicit mode parameters select a data source. Roles and display density are independent. */
export function workspaceMode(params: { get(key: string): string | null }) {
  const preview = params.get("preview");
  if (preview === "1" || preview === "awaiting") return "sample";
  // Live SSE is the default dashboard; the browser-only dental demo is opt-in.
  return params.get("workspace") === "demo" ? "demo" : "live";
}
