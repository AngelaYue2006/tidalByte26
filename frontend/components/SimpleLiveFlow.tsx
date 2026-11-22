"use client";

import WorkspaceLink from "./WorkspaceLink";
import { useEffect, useState } from "react";
import { IconCalendar, IconPhone } from "@tabler/icons-react";
import type { ProjectedDashboard } from "@/lib/project";
import { VIEWERS, type Viewer } from "@/lib/viewer";
import { postRequest } from "@/lib/api";
import {
  enrichRequestText,
  knownPreferences,
  missingFields,
  readDraft,
  saveDraft,
  type DentalPreferences,
  type IntakeDraft,
} from "@/lib/demoIntake";
import SimplePanel from "./SimplePanel";
import RequestBar from "./RequestBar";
import DemoIntakeQuestion from "./DemoIntakeQuestion";
import DecisionCard from "./DecisionCard";
import ContactReply from "./ContactReply";
import RecordedCallGraphs from "./RecordedCallGraphs";
import CallStrip from "./CallStrip";

function newIdempotencyKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `req-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

export default function SimpleLiveFlow({ state, viewer, taskId, demo, error }: {
  state: ProjectedDashboard; viewer: Viewer; taskId?: string; demo: boolean; error: string | null;
}) {
  const [sent, setSent] = useState(false);
  const [watch, setWatch] = useState(false);
  const [draft, setDraft] = useState<IntakeDraft | null>(null);
  const [pendingText, setPendingText] = useState("");
  const [ready, setReady] = useState(false);
  const [postError, setPostError] = useState<string | null>(null);
  const contact = viewer.role === "contact";
  const booked = state.confirmations?.booked;
  const ended = state.calls.length > 0 && state.calls.every(call => call.status === "done" || call.result);
  const failed = state.taskStatus === "failed" || state.taskStatus === "cancelled";
  const reviewing = !!(state.approval || state.decision || ended);
  const started = sent || state.request || state.calls.length > 0 || state.taskId;
  const ride = <ContactReply viewer={viewer} taskId={taskId} awaitingReply={state.canReplyRide} hasReply={!!state.contact?.reply}/>;

  useEffect(() => {
    setDraft(readDraft());
    setReady(true);
  }, []);

  function changeDraft(next: IntakeDraft | null) {
    saveDraft(next);
    setDraft(next);
  }

  async function startSearch(text: string, preferences: DentalPreferences) {
    setPostError(null);
    changeDraft(null);
    if (demo) {
      setSent(true);
      return;
    }
    try {
      await postRequest(viewer.viewerId, {
        owner_id: VIEWERS.owner.viewerId,
        actor_id: viewer.viewerId,
        text: enrichRequestText(text, preferences),
        idempotency_key: newIdempotencyKey(),
      });
      setSent(true);
      setPendingText("");
    } catch (err) {
      setPostError(err instanceof Error ? err.message : "Could not send request");
    }
  }

  function submitRequest(text: string) {
    const known = knownPreferences(text);
    setPendingText(text);
    if (missingFields(known).length) changeDraft({ known, answers: {}, index: 0 });
    else void startSearch(text, known);
  }

  if (!ready) return <main aria-busy="true"/>;

  if (!started && draft) {
    if (contact) {
      return (
        <main className="simple-main">
          <SimplePanel stage="request" title="Waiting for Mary">
            <p>Mary has a question to answer in her view before AIGranni calls clinics.</p>
          </SimplePanel>
        </main>
      );
    }
    return (
      <DemoIntakeQuestion
        key={draft.index}
        draft={draft}
        change={changeDraft}
        finish={(preferences) => void startSearch(pendingText, preferences)}
        demo={demo}
      />
    );
  }

  if (watch && started && !reviewing && !booked && !failed) return <main className="view-enter">
    <div className="studio-heading"><h1>Watch the agents</h1><button className="quiet-button" onClick={() => setWatch(false)}>{contact ? "Back to Mary’s request" : "Back to my request"}</button></div>
    <CallStrip calls={state.calls}/>
    {viewer.role === "owner" && <RecordedCallGraphs calls={state.calls} animate/>}
    {!state.calls.length && <p role="status">Preparing the clinic calls…</p>}
  </main>;
  return <main className="simple-main">
    {booked ? <SimplePanel stage="appointment" demo={demo} title={booked.tentative ? "Waiting for confirmation" : contact ? "Mary’s booked appointment" : "Your booked appointment"}>
      <div className="appointment-summary"><strong>{booked.calendar.replace(/<[^>]+>/g, " ")}</strong></div>
      {!booked.tentative && <WorkspaceLink className="primary-action" href="/calendar"><IconCalendar/>{contact ? "View Mary’s calendar" : "View my calendar"}</WorkspaceLink>}
      {ride}
    </SimplePanel> : failed ? <SimplePanel stage="request" title="Try another request">
      <p>The previous request ended without a booking.</p>
      <RequestBar viewer={viewer} simple demo onSent={submitRequest}/>
      {postError && <p role="alert">{postError}</p>}
    </SimplePanel> : reviewing ? <SimplePanel stage="appointment" demo={demo} title={contact ? "Clinic calls for Mary are complete" : "Your calls are complete"}>
      {contact ? <p>Mary will review the appointment offer.</p> : state.decision && state.approval ? <DecisionCard viewer={viewer} decision={state.decision} approval={state.approval} taskId={taskId} compact/> :
        <p role="status">Checking the clinic offers for your appointment.</p>}
      {ride}
    </SimplePanel> : started || state.canReplyRide ? <SimplePanel stage="calls" title={contact ? "Mary’s request is in" : "Your request is in"}>
      <p>AIGranni is checking clinics. You can watch the agents or wait here.</p>
      <button className="primary-action" onClick={() => setWatch(true)}><IconPhone/>Watch the agents</button>{ride}
    </SimplePanel> : <SimplePanel stage="request" title={contact ? "What does Mary need to book?" : "What can we help you book?"}>
      <RequestBar viewer={viewer} simple demo onSent={submitRequest}/>
      {postError && <p role="alert">{postError}</p>}
    </SimplePanel>}
    {error && !demo && <p role="status" className="muted">{error}</p>}
  </main>;
}
