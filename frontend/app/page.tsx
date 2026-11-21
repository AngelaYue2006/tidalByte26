// Live dashboard placeholder. Sections land in later issues: RequestBar, CallCards, DecisionCard, TransportCard, Confirmations.
import { Suspense } from "react";
import LivePlaceholder from "@/components/LivePlaceholder";

export default function Page() {
  return (
    <Suspense fallback={<main className="card"><p className="muted">Loading…</p></main>}>
      <LivePlaceholder />
    </Suspense>
  );
}
