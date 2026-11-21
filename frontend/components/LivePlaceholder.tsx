"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import DecisionCard from "@/components/DecisionCard";
import RequestBar from "@/components/RequestBar";
import { foldEvents, type DashboardState } from "@/lib/dashboard";
import type { LiveEvent } from "@/lib/events";
import { connectLive, liveUrl } from "@/lib/live";
import { PROTOTYPE_SCENARIO } from "@/lib/scenario";
import { viewerFromSearchParams } from "@/lib/viewer";

const PREVIEW_REQUEST = PROTOTYPE_SCENARIO.find((e) => e.type === "request");

const PREVIEW_EVENTS: LiveEvent[] = [
  ...PROTOTYPE_SCENARIO,
  {
    type: "approval_required",
    pick: { clinic: "Bright Smile Dental", slot: "Thu 9:30", price: "$95" },
    expires_at: "in 10 min",
  },
];

const PREVIEW_APPROVED_EVENTS: LiveEvent[] = [
  ...PREVIEW_EVENTS,
  { type: "approved", by: "Mary Johnson", via: "dashboard" },
];

const PREVIEW_STATE = foldEvents(PREVIEW_EVENTS);
const PREVIEW_APPROVED_STATE = foldEvents(PREVIEW_APPROVED_EVENTS);

/** Live page shell: RequestBar + DecisionCard; call/transport cards land in sibling PRs. */
export default function LivePlaceholder() {
  const searchParams = useSearchParams();
  const viewer = viewerFromSearchParams(searchParams);
  const preview = searchParams.get("preview") === "1";
  const previewApproved = searchParams.get("preview") === "approved";
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
    if (liveState?.decision) return liveState;
    if (previewApproved) return PREVIEW_APPROVED_STATE;
    if (preview) return PREVIEW_STATE;
    return liveState;
  }, [liveState, preview, previewApproved]);

  const mode = process.env.NEXT_PUBLIC_LIVE_STREAM_MODE ?? "sse";
  const chips =
    state?.request?.chips ??
    ((preview || previewApproved) && PREVIEW_REQUEST?.type === "request"
      ? PREVIEW_REQUEST.chips
      : undefined);
  const liveText = viewer.role === "owner" ? state?.request?.text : undefined;
  const requestText =
    liveText ??
    ((preview || previewApproved) &&
    viewer.role === "owner" &&
    PREVIEW_REQUEST?.type === "request"
      ? PREVIEW_REQUEST.text
      : undefined);

  const taskId = state?.taskId ?? (preview || previewApproved ? "preview-task" : undefined);

  return (
    <main>
      <RequestBar viewer={viewer} chips={chips} requestText={requestText} />

      {state?.decision ? (
        <DecisionCard
          viewer={viewer}
          decision={state.decision}
          approval={state.approval}
          taskId={taskId}
        />
      ) : null}

      <div className="card">
        <h1 className="placeholder-title">Next steps</h1>
        <p className="placeholder-body">
          Call cards, transport and confirmations land in later gate issues.
        </p>
        <p className="faint placeholder-meta">
          {mode === "poll" ? "Poll mode" : "SSE"} → <code>{sse}</code>
          {preview || previewApproved ? " · preview scenario" : ""}
        </p>
        {error ? <p className="faint placeholder-meta">{error}</p> : null}
      </div>
    </main>
  );
}
