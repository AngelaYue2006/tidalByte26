// History detail: event trail and (owner) call transcripts.
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
