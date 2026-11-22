// History detail for recorded requests and the local simulated session.
import { Suspense } from "react";
import HistoryDetailPage from "@/components/HistoryDetailPage";

type Props = { params: Promise<{ id: string }> };

export default async function HistoryDetailRoute({ params }: Props) {
  const { id } = await params;
  return (
    <Suspense fallback={<main><p className="muted">Loading…</p></main>}>
      <HistoryDetailPage taskId={decodeURIComponent(id)} />
    </Suspense>
  );
}
