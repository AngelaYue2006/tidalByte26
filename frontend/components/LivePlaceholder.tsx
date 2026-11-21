"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import RequestBar from "@/components/RequestBar";
import type { DashboardState } from "@/lib/dashboard";
import { connectLive, liveUrl } from "@/lib/live";
import { PROTOTYPE_SCENARIO } from "@/lib/scenario";
import { viewerFromSearchParams } from "@/lib/viewer";

const PREVIEW_REQUEST = PROTOTYPE_SCENARIO.find((e) => e.type === "request");

/** Live page shell: RequestBar + SSE state; call/decision cards land in later issues. */
export default function LivePlaceholder() {
  const searchParams = useSearchParams();
  const viewer = viewerFromSearchParams(searchParams);
  const preview = searchParams.get("preview") === "1";
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
  const chips = state?.request?.chips ?? (preview && PREVIEW_REQUEST?.type === "request" ? PREVIEW_REQUEST.chips : undefined);
  // Contact never sees request.text (owner-only).
  const liveText = viewer.role === "owner" ? state?.request?.text : undefined;
  const requestText =
    liveText ??
    (preview && viewer.role === "owner" && PREVIEW_REQUEST?.type === "request"
      ? PREVIEW_REQUEST.text
      : undefined);

  return (
    <main>
      <RequestBar
        viewer={viewer}
        chips={chips}
        requestText={requestText}
      />
      <div className="card">
        <h1 className="placeholder-title">Live trail</h1>
        <p className="placeholder-body">
          Call cards, decision and confirmations land in later gate issues.
        </p>
        <p className="faint placeholder-meta">
          {mode === "poll" ? "Poll mode" : "SSE"} → <code>{sse}</code>
          {state ? ` · ${callCount} call${callCount === 1 ? "" : "s"} in state` : ""}
        </p>
        {error ? <p className="faint placeholder-meta">{error}</p> : null}
      </div>
    </main>
  );
}
