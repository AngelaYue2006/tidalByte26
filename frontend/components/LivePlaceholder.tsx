"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import type { DashboardState } from "@/lib/dashboard";
import { connectLive, liveUrl } from "@/lib/live";
import { viewerFromSearchParams } from "@/lib/viewer";

/** Live page shell: connects SSE (or poll) for this viewer; event cards land in later issues. */
export default function LivePlaceholder() {
  const viewer = viewerFromSearchParams(useSearchParams());
  const sse = liveUrl(viewer.viewerId);
  const [state, setState] = useState<DashboardState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    const close = connectLive(viewer.viewerId, {
      onState: setState,
      onError: () => setError("Live stream interrupted — reconnecting…"),
    });
    return close;
  }, [viewer.viewerId]);

  const mode = process.env.NEXT_PUBLIC_LIVE_STREAM_MODE ?? "sse";
  const callCount = state?.calls.length ?? 0;

  return (
    <main>
      <div className="card">
        <h1 className="placeholder-title">Live dashboard</h1>
        <p className="placeholder-body">
          Viewing as <strong>{viewer.name}</strong> ({viewer.role}). Request, calls, decision and
          confirmations land in later gate issues.
        </p>
        <p className="faint placeholder-meta">
          {mode === "poll" ? "Poll mode" : "SSE"} → <code>{sse}</code>
          {state ? ` · ${callCount} call${callCount === 1 ? "" : "s"} in state` : ""}
          {state?.request ? ` · request chips: ${state.request.chips.length}` : ""}
        </p>
        {error ? <p className="faint placeholder-meta">{error}</p> : null}
      </div>
    </main>
  );
}
