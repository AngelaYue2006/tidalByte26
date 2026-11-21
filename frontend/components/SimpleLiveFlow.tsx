"use client";

import WorkspaceLink from "./WorkspaceLink";
import { useState } from "react";
import { IconCalendar, IconPhone } from "@tabler/icons-react";
import type { ProjectedDashboard } from "@/lib/project";
import type { Viewer } from "@/lib/viewer";
import SimplePanel from "./SimplePanel";
import RequestBar from "./RequestBar";
import DecisionCard from "./DecisionCard";
import ContactReply from "./ContactReply";
import RecordedCallGraphs from "./RecordedCallGraphs";
import CallStrip from "./CallStrip";

export default function SimpleLiveFlow({ state, viewer, taskId, demo, error }: {
  state: ProjectedDashboard; viewer: Viewer; taskId?: string; demo: boolean; error: string | null;
}) {
  const [sent, setSent] = useState(false);
  const [watch, setWatch] = useState(false);
  const contact = viewer.role === "contact";
  const booked = state.confirmations?.booked;
  const ended = state.calls.length > 0 && state.calls.every(call => call.status === "done" || call.result);
  const failed = state.taskStatus === "failed" || state.taskStatus === "cancelled";
  const reviewing = !!(state.approval || state.decision || ended);
  const started = sent || state.request || state.calls.length > 0 || state.taskId;
  const ride = <ContactReply viewer={viewer} taskId={taskId} awaitingReply={state.canReplyRide} hasReply={!!state.contact?.reply}/>;

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
      <RequestBar viewer={viewer} simple onSent={() => setSent(true)}/>
    </SimplePanel> : reviewing ? <SimplePanel stage="appointment" demo={demo} title={contact ? "Clinic calls for Mary are complete" : "Your calls are complete"}>
      {contact ? <p>Mary will review the appointment offer.</p> : state.decision && state.approval ? <DecisionCard viewer={viewer} decision={state.decision} approval={state.approval} taskId={taskId} compact/> :
        <p role="status">Checking the clinic offers for your appointment.</p>}
      {ride}
    </SimplePanel> : started || state.canReplyRide ? <SimplePanel stage="calls" title={contact ? "Mary’s request is in" : "Your request is in"}>
      <p>LifeLine is checking clinics. You can watch the agents or wait here.</p>
      <button className="primary-action" onClick={() => setWatch(true)}><IconPhone/>Watch the agents</button>{ride}
    </SimplePanel> : <SimplePanel stage="request" title={contact ? "What does Mary need to book?" : "What can we help you book?"}>
      <RequestBar viewer={viewer} simple onSent={() => setSent(true)}/>
    </SimplePanel>}
    {error && !demo && <p role="status" className="muted">{error}</p>}
  </main>;
}
