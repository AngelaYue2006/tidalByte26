/** Only explicit mode parameters select a data source. Roles and display density are independent. */
export function workspaceMode(params: { get(key: string): string | null }) {
  const preview = params.get("preview");
  if (preview === "1" || preview === "awaiting") return "sample";
  return params.get("workspace") === "live" ? "live" : "demo";
}
