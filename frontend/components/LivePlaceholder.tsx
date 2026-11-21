"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import CallCard from "@/components/CallCard";
import Confirmations from "@/components/Confirmations";
import ContactReply from "@/components/ContactReply";
import DecisionCard from "@/components/DecisionCard";
import RequestBar from "@/components/RequestBar";
import TransportCard from "@/components/TransportCard";
import { foldEvents, type DashboardState } from "@/lib/dashboard";
import type { LiveEvent } from "@/lib/events";
import { connectLive, liveUrl } from "@/lib/live";
import { projectForViewer } from "@/lib/project";
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

const APPROVAL_EVENTS: LiveEvent[] = [
  {
    type: "approval_required",
    pick: { clinic: "Bright Smile Dental", slot: "Thu 9:30", price: "$95" },
    expires_at: "in 10 min",
  },
];

/** Full demo trail including approval + transport + confirmations. */
const PREVIEW_EVENTS: LiveEvent[] = [
  ...PROTOTYPE_SCENARIO.filter((e) => e.type !== "booked" && e.type !== "notified"),
  ...APPROVAL_EVENTS,
  { type: "approved", by: "Mary Johnson", via: "dashboard" },
  ...TRANSPORT_EVENTS,
  ...PROTOTYPE_SCENARIO.filter((e) => e.type === "booked" || e.type === "notified"),
];
const PREVIEW_STATE = foldEvents(PREVIEW_EVENTS);

/** Owner mid-approval + contact awaiting ride reply. */
const AWAITING_EVENTS: LiveEvent[] = [
  ...PROTOTYPE_SCENARIO.filter((e) => e.type !== "booked" && e.type !== "notified"),
  ...APPROVAL_EVENTS,
  TRANSPORT_EVENTS[0],
  TRANSPORT_EVENTS[1],
];
const AWAITING_STATE = foldEvents(AWAITING_EVENTS);

/** Live page with role-scoped projection for owner and contact. */
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

  const rawState = useMemo(() => {
    // Prefer any real stream state (including request-only / taskId) over the fixture preview.
    const hasLive =
      !!liveState &&
      (!!liveState.taskId ||
        !!liveState.request ||
        liveState.calls.length > 0 ||
        !!liveState.transport ||
        !!liveState.decision ||
        !!liveState.approval ||
        !!liveState.confirmations);
    if (hasLive) return liveState!;
    if (previewAwaiting) return AWAITING_STATE;
    if (preview) return PREVIEW_STATE;
    return liveState ?? { calls: [] };
  }, [liveState, preview, previewAwaiting]);

  const state = useMemo(
    () => projectForViewer(rawState, viewer.role),
    [rawState, viewer.role],
  );

  const mode = process.env.NEXT_PUBLIC_LIVE_STREAM_MODE ?? "sse";
  const chips =
    state.request?.chips ??
    ((preview || previewAwaiting) && PREVIEW_REQUEST?.type === "request"
      ? PREVIEW_REQUEST.chips
      : undefined);
  // Projection already stripped text for contact; never pass raw text as fallback for contact.
  const requestText =
    viewer.role === "owner"
      ? (state.request?.text ??
        ((preview || previewAwaiting) && PREVIEW_REQUEST?.type === "request"
          ? PREVIEW_REQUEST.text
          : undefined))
      : undefined;
  const winnerId = state.decision?.winner;
  const calls = state.calls;
  const taskId =
    state.taskId ?? (preview || previewAwaiting ? "preview-task" : undefined);
  const showConfirmations = !!state.confirmations?.booked || !!state.confirmations?.notified;

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

      {state.decision ? (
        <DecisionCard
          viewer={viewer}
          decision={state.decision}
          approval={state.approval}
          taskId={taskId}
        />
      ) : null}

      <TransportCard
        transport={state.transport}
        contact={state.contact}
        ride={state.confirmations?.ride}
      />

      <ContactReply
        viewer={viewer}
        taskId={taskId}
        awaitingReply={state.canReplyRide}
        hasReply={!!state.contact?.reply}
      />

      {viewer.role === "owner" && state.contact?.message && !state.contact?.reply ? (
        <div className="card status-card">
          <p className="muted status-card-text">
            Waiting for {state.contact.name ?? "the contact"} to reply about the ride.
          </p>
        </div>
      ) : null}

      <Confirmations confirmations={state.confirmations} show={showConfirmations} />

      <div className="card status-card">
        <p className="faint placeholder-meta status-card-text">
          Viewing as <strong>{viewer.role}</strong>
          {" · "}
          {mode === "poll" ? "Poll mode" : "SSE"} → <code>{sse}</code>
          {preview || previewAwaiting ? " · preview" : ""}
        </p>
        {error ? <p className="faint placeholder-meta">{error}</p> : null}
      </div>
    </main>
  );
}
