// Live dashboard. RequestBar is live; CallCards, DecisionCard, TransportCard, Confirmations follow.
import { Suspense } from "react";
import LivePlaceholder from "@/components/LivePlaceholder";

export default function Page() {
  return (
    <Suspense fallback={<main className="card"><p className="muted">Loading…</p></main>}>
      <LivePlaceholder />
    </Suspense>
  );
}
