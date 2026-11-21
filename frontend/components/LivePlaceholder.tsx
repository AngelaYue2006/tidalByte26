"use client";

import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import BookingHero from "@/components/BookingHero";
import CallCard from "@/components/CallCard";
import CallStrip from "@/components/CallStrip";
import Confirmations from "@/components/Confirmations";
import ContactReply from "@/components/ContactReply";
import DecisionCard from "@/components/DecisionCard";
import RequestBar from "@/components/RequestBar";
import SceneArt from "@/components/SceneArt";
import TransportCard from "@/components/TransportCard";
import { foldEvents, type DashboardState } from "@/lib/dashboard";
import { densityFromSearchParams } from "@/lib/density";
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

/** Live page with role-scoped projection and simple/detailed density. */
export default function LivePlaceholder() {
  const searchParams = useSearchParams();
  const viewer = viewerFromSearchParams(searchParams);
  const density = densityFromSearchParams(searchParams, viewer.role);
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
    if (liveState && (liveState.calls.length > 0 || liveState.transport || liveState.decision)) {
      return liveState;
    }
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
  const simple = density === "simple";

  return (
    <main className={simple ? "live-main density-simple" : "live-main density-detailed"} key={density}>
      <header className="page-hero card page-hero-live">
        <div className="page-hero-copy">
          <p className="page-kicker">In progress</p>
          <h1>Live</h1>
          <p className="muted">
            {viewer.role === "owner"
              ? "Speak a request — LifeLine calls clinics, picks a slot, and waits for your OK."
              : "Watch Mary’s booking trail. Reply when a ride is needed."}
          </p>
        </div>
        <SceneArt name="phone" className="scene-art page-hero-art" />
      </header>

      <section className="live-section live-section-request">
        <RequestBar viewer={viewer} chips={chips} requestText={requestText} />
      </section>

      {simple ? (
        <>
          <CallStrip calls={calls} winnerId={winnerId} />
          <BookingHero
            decision={state.decision}
            approval={state.approval}
            confirmations={state.confirmations}
          />
          {state.decision && state.approval?.pick && !state.approval?.approved ? (
            <DecisionCard
              viewer={viewer}
              decision={state.decision}
              approval={state.approval}
              taskId={taskId}
              compact
            />
          ) : null}
          <ContactReply
            viewer={viewer}
            taskId={taskId}
            awaitingReply={state.canReplyRide}
            hasReply={!!state.contact?.reply}
          />
        </>
      ) : (
        <>
          <section className="live-section live-section-calls">
            {calls.length > 0 ? (
              <div className="calls" aria-label="Clinic calls">
                {calls.map((call) => (
                  <CallCard
                    key={call.call_id}
                    call={call}
                    winner={winnerId === call.call_id}
                  />
                ))}
              </div>
            ) : null}
          </section>

          <section className="live-section live-section-decision">
            {state.decision ? (
              <DecisionCard
                viewer={viewer}
                decision={state.decision}
                approval={state.approval}
                taskId={taskId}
              />
            ) : null}
          </section>

          <section className="live-section live-section-transport">
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
          </section>

          <section className="live-section live-section-confirm">
            <Confirmations confirmations={state.confirmations} show={showConfirmations} />
          </section>
        </>
      )}

      <div className="card status-card live-meta">
        <p className="faint placeholder-meta status-card-text">
          Viewing as <strong>{viewer.role}</strong>
          {" · "}
          <strong>{density}</strong> view
          {" · "}
          {mode === "poll" ? "Poll mode" : "SSE"} → <code>{sse}</code>
          {preview || previewAwaiting ? " · preview" : ""}
        </p>
        {error ? <p className="faint placeholder-meta">{error}</p> : null}
      </div>
    </main>
  );
}
