// History placeholder. Full trail from GET /api/tasks lands in a later issue.
import { Suspense } from "react";
import HistoryPlaceholder from "@/components/HistoryPlaceholder";

export default function HistoryPage() {
  return (
    <Suspense fallback={<main className="card"><p className="muted">Loading…</p></main>}>
      <HistoryPlaceholder />
    </Suspense>
  );
}
