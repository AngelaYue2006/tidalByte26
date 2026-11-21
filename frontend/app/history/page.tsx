// History list from GET /api/tasks — newest first, viewer-scoped.
import { Suspense } from "react";
import HistoryPage from "@/components/HistoryPage";

export default function HistoryRoute() {
  return (
    <Suspense fallback={<main><p className="muted">Loading…</p></main>}>
      <HistoryPage />
    </Suspense>
  );
}
