"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import CallCard from "@/components/CallCard";
import RequestBar from "@/components/RequestBar";
import { foldEvents, type DashboardState } from "@/lib/dashboard";
import { connectLive, liveUrl } from "@/lib/live";
import { PROTOTYPE_SCENARIO } from "@/lib/scenario";
import { viewerFromSearchParams } from "@/lib/viewer";

const PREVIEW_REQUEST = PROTOTYPE_SCENARIO.find((e) => e.type === "request");
const PREVIEW_STATE = foldEvents(PROTOTYPE_SCENARIO);

/** Live page shell: RequestBar + CallCards; decision/transport land later. */
export default function LivePlaceholder() {
  const searchParams = useSearchParams();
  const viewer = viewerFromSearchParams(searchParams);
  const preview = searchParams.get("preview") === "1";
  const sse = liveUrl(viewer.viewerId);
  const [liveState, setLiveState] = useState<DashboardState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    const close = connectLive(viewer.viewerId, {
      onState: setLiveState,
      onError: () => setError("Live stream interrupted — reconnecting…"),
    });
    return close;
  }, [viewer.viewerId]);

  const state = useMemo(() => {
    if (liveState && (liveState.calls.length > 0 || liveState.request)) return liveState;
    return preview ? PREVIEW_STATE : liveState;
  }, [liveState, preview]);

  const mode = process.env.NEXT_PUBLIC_LIVE_STREAM_MODE ?? "sse";
  const chips =
    state?.request?.chips ??
    (preview && PREVIEW_REQUEST?.type === "request" ? PREVIEW_REQUEST.chips : undefined);
  const liveText = viewer.role === "owner" ? state?.request?.text : undefined;
  const requestText =
    liveText ??
    (preview && viewer.role === "owner" && PREVIEW_REQUEST?.type === "request"
      ? PREVIEW_REQUEST.text
      : undefined);
  const winnerId = state?.decision?.winner;
  const calls = state?.calls ?? [];

  return (
    <main>
      <RequestBar viewer={viewer} chips={chips} requestText={requestText} />

      {calls.length > 0 ? (
        <section className="calls" aria-label="Clinic calls">
          {calls.map((call) => (
            <CallCard
              key={call.call_id}
              call={call}
              winner={winnerId === call.call_id}
            />
          ))}
        </section>
      ) : null}

      <div className="card">
        <h1 className="placeholder-title">Next steps</h1>
        <p className="placeholder-body">
          Decision, approval, transport and confirmations land in later gate issues.
        </p>
        <p className="faint placeholder-meta">
          {mode === "poll" ? "Poll mode" : "SSE"} → <code>{sse}</code>
          {preview && !liveState?.calls.length ? " · preview scenario" : ""}
        </p>
        {error ? <p className="faint placeholder-meta">{error}</p> : null}
      </div>
    </main>
  );
}
