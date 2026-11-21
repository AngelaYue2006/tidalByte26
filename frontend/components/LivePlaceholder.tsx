"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import CallCard from "@/components/CallCard";
import Confirmations from "@/components/Confirmations";
import ContactReply from "@/components/ContactReply";
import RequestBar from "@/components/RequestBar";
import TransportCard from "@/components/TransportCard";
import { foldEvents, type DashboardState } from "@/lib/dashboard";
import type { LiveEvent } from "@/lib/events";
import { connectLive, liveUrl } from "@/lib/live";
import { PROTOTYPE_SCENARIO } from "@/lib/scenario";
import { viewerFromSearchParams } from "@/lib/viewer";

const PREVIEW_REQUEST = PROTOTYPE_SCENARIO.find((e) => e.type === "request");

const TRANSPORT_EVENTS: LiveEvent[] = [
  {
    type: "transport_check",
    status: "unavailable",
    reason: "No wheelchair-accessible vehicles in range this week.",
    simulated: true,
  },
  {
    type: "contact_request",
    contact: "Sarah (daughter)",
    message:
      "LifeLine: Mary needs a ride to Bright Smile Dental, Thu Nov 26 at 9:30 AM, 123 Main St. Can you drive?",
  },
  {
    type: "contact_reply",
    contact: "Sarah (daughter)",
    text: "I can drive — I'll pick her up at 9:00.",
    offer: { can_drive: true, pickup_time: "9:00 AM" },
  },
  {
    type: "ride_confirmed",
    driver: "Sarah (daughter)",
    pickup_time: "Thu 9:00 AM",
  },
];

const PREVIEW_EVENTS: LiveEvent[] = [...PROTOTYPE_SCENARIO, ...TRANSPORT_EVENTS];
const PREVIEW_STATE = foldEvents(PREVIEW_EVENTS);

/** Awaiting-reply preview: transport + contact_request only (for contact buttons). */
const AWAITING_EVENTS: LiveEvent[] = [
  ...PROTOTYPE_SCENARIO.filter((e) => e.type !== "booked" && e.type !== "notified"),
  TRANSPORT_EVENTS[0],
  TRANSPORT_EVENTS[1],
];
const AWAITING_STATE = foldEvents(AWAITING_EVENTS);

/** Live page: RequestBar, CallCards, transport/contact, confirmations. */
export default function LivePlaceholder() {
  const searchParams = useSearchParams();
  const viewer = viewerFromSearchParams(searchParams);
  const preview = searchParams.get("preview") === "1";
  const previewAwaiting = searchParams.get("preview") === "awaiting";
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
    if (liveState && (liveState.calls.length > 0 || liveState.transport || liveState.confirmations)) {
      return liveState;
    }
    if (previewAwaiting) return AWAITING_STATE;
    if (preview) return PREVIEW_STATE;
    return liveState;
  }, [liveState, preview, previewAwaiting]);

  const mode = process.env.NEXT_PUBLIC_LIVE_STREAM_MODE ?? "sse";
  const chips =
    state?.request?.chips ??
    ((preview || previewAwaiting) && PREVIEW_REQUEST?.type === "request"
      ? PREVIEW_REQUEST.chips
      : undefined);
  const liveText = viewer.role === "owner" ? state?.request?.text : undefined;
  const requestText =
    liveText ??
    ((preview || previewAwaiting) &&
    viewer.role === "owner" &&
    PREVIEW_REQUEST?.type === "request"
      ? PREVIEW_REQUEST.text
      : undefined);
  const winnerId = state?.decision?.winner;
  const calls = state?.calls ?? [];
  const taskId =
    state?.taskId ?? (preview || previewAwaiting ? "preview-task" : undefined);
  const awaitingReply = !!state?.contact?.message && !state?.contact?.reply;
  const showConfirmations = !!state?.confirmations?.booked || !!state?.confirmations?.notified;

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

      <TransportCard
        transport={state?.transport}
        contact={state?.contact}
        ride={state?.confirmations?.ride}
      />

      <ContactReply
        viewer={viewer}
        taskId={taskId}
        awaitingReply={awaitingReply}
        hasReply={!!state?.contact?.reply}
      />

      {viewer.role === "owner" && awaitingReply ? (
        <div className="card status-card">
          <p className="muted status-card-text">
            Waiting for {state?.contact?.name ?? "the contact"} to reply about the ride.
          </p>
        </div>
      ) : null}

      <Confirmations confirmations={state?.confirmations} show={showConfirmations} />

      <div className="card status-card">
        <p className="faint placeholder-meta status-card-text">
          {mode === "poll" ? "Poll mode" : "SSE"} → <code>{sse}</code>
          {preview || previewAwaiting ? " · preview scenario" : ""}
        </p>
        {error ? <p className="faint placeholder-meta">{error}</p> : null}
      </div>
    </main>
  );
}
