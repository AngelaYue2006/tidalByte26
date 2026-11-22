"use client";

import WorkspaceLink from "./WorkspaceLink";
import { useEffect, useState } from "react";
import { IconCalendar, IconPhone } from "@tabler/icons-react";
import DemoIntakeQuestion from "./DemoIntakeQuestion";
import { knownPreferences, missingFields, readDraft, saveDraft, type IntakeDraft, type DentalPreferences } from "@/lib/demoIntake";
import CallDemo from "./CallDemo";
import RequestBar from "./RequestBar";
import SimplePanel from "./SimplePanel";
import { archiveDemo, clinics, demoEnd, elapsedSeconds, readDemoRun, saveDemoRun, type DemoRun } from "@/lib/callDemo";
import type { Viewer } from "@/lib/viewer";

export default function DemoRequestFlow({ viewer }: { viewer: Viewer }) {
  const contact = viewer.role === "contact";
  const [run, setRun] = useState<DemoRun | null>(null);
  const [draft, setDraft] = useState<IntakeDraft | null>(null);
  const [ready, setReady] = useState(false);
  const [watch, setWatch] = useState(false);
  const [now, setNow] = useState(Date.now);
  useEffect(() => { setRun(readDemoRun()); setDraft(readDraft()); setReady(true); }, []);
  const elapsed = run ? elapsedSeconds(run, now) : 0;
  const finished = elapsed >= demoEnd;
  useEffect(() => {
    if (!run || finished || run.pausedAt !== null) return;
    const tick = window.setInterval(() => setNow(Date.now()), 250);
    return () => clearInterval(tick);
  }, [run, finished]);
  function update(next: DemoRun | null) {
    saveDemoRun(next);
    setNow(Date.now());
    setRun(next);
  }
  function changeWatch(value: boolean) {
    setWatch(value);
    window.scrollTo(0, 0);
  }
  useEffect(() => {
    if (finished) archiveDemo(run?.approved ?? false, run?.preferences);
    if (finished && watch) { setWatch(false); window.scrollTo(0, 0); }
  }, [finished, watch, run?.approved, run?.preferences]);

  function changeDraft(next: IntakeDraft | null) {
    saveDraft(next);
    setDraft(next);
  }
  function beginCalls(preferences: DentalPreferences) {
    update({ started: Date.now(), pausedAt: null, approved: false, preferences });
    changeDraft(null);
  }
  function submitRequest(text: string) {
    const known = knownPreferences(text);
    if (missingFields(known).length) changeDraft({ known, answers: {}, index: 0 });
    else beginCalls(known);
  }
  if (!ready) return <main aria-busy="true"/>;
  if (!run && draft) {
    if (contact) return <main className="simple-main"><SimplePanel demo stage="request" title="Waiting for Mary">
      <p>Mary has a question to answer in her view before LifeLine calls clinics.</p>
    </SimplePanel></main>;
    return <DemoIntakeQuestion key={draft.index} draft={draft} change={changeDraft} finish={beginCalls}/>;
  }
  if (run && watch && !finished) return <main className="view-enter">
    <CallDemo elapsed={elapsed} budget={run.preferences?.budget} paused={run.pausedAt !== null} back={() => {
      if (run.pausedAt !== null) update({ ...run, started: run.started + Date.now() - run.pausedAt, pausedAt: null });
      changeWatch(false);
    }} togglePause={() => {
      const time = Date.now();
      update(run.pausedAt === null ? { ...run, pausedAt: time } :
        { ...run, started: run.started + time - run.pausedAt, pausedAt: null });
    }}/>
  </main>;
  const clinic = clinics[0];
  const cap = run?.preferences?.budget;
  if (run && finished && typeof cap === "number" && clinic.price > cap) return <main className="simple-main">
    <SimplePanel demo stage="appointment" title={contact ? "Mary’s search is complete" : "No appointment within your budget"}>
      <p>{contact ? "Mary has no simulated booking from this search." : `The lowest simulated offer is $95, above your $${cap} maximum.`}</p>
      {!contact && <button className="primary-action" onClick={() => update(null)}>Start a new request</button>}
    </SimplePanel></main>;
  if (contact && run) return <main className="simple-main">
    <SimplePanel demo stage={finished ? "appointment" : "calls"} title={run.approved ? "Mary’s demo appointment" : finished ? "Waiting for Mary’s approval" : "Finding an appointment for Mary"}>
      {run.approved ? <>
        <p>Mary approved this simulated booking.</p>
        <div className="appointment-summary"><strong>Dental cleaning for Mary</strong><span>{clinic.name}</span><span>Thursday, November 26 at 9:30 AM</span></div>
        <WorkspaceLink className="primary-action" href="/calendar"><IconCalendar/>View Mary’s calendar</WorkspaceLink>
      </> : <p>{finished ? "Mary can review the suggested appointment in her view." : "Three agents are calling clinics on Mary’s behalf."}</p>}
      <p>No action is needed from you, Sarah.</p>
    </SimplePanel>
  </main>;
  return <main className="simple-main">
    {!run ? <SimplePanel stage="request" title={contact ? "What does Mary need to book?" : "What can we help you book?"} demo>
      <p>{contact ? "Send a simulated request on Mary’s behalf." : "Try a request with three simulated dental clinics."}</p>
      <RequestBar viewer={viewer} simple demo onSent={submitRequest}/>
    </SimplePanel> : !finished ? <SimplePanel stage="calls" title="Your request is in" demo>
      <p>Three agents are calling clinics. You can follow their conversations or wait here for the result.</p>
      <button className="primary-action" onClick={() => changeWatch(true)}><IconPhone/>Watch the agents</button>
    </SimplePanel> : <SimplePanel demo stage="appointment" title={run.approved ? "Your demo appointment" : "Your calls are complete"}>
      <p>{run.approved ? "You approved this simulated booking. It stays here until you start a new request." : "Review the suggested appointment before approving the simulated booking."}</p>
      <div className="appointment-summary"><strong>Dental cleaning</strong><span>{clinic.name}</span><span>Thursday, November 26 at 9:30 AM · $95</span></div>
      {run.preferences?.ride !== undefined && <p>{run.preferences.ride ? "Ride preference: help requested." : "Ride preference: arranging your own ride."}</p>}
      {run.approved ? <WorkspaceLink className="primary-action" href="/calendar"><IconCalendar/>View my calendar</WorkspaceLink> :
        <button className="primary-action" onClick={() => update({ ...run, approved: true })}>Approve demo appointment</button>}
      <div className="secondary-actions"><WorkspaceLink href="/history/demo-cleaning">Review agent calls</WorkspaceLink>
        <button className="quiet-button" onClick={() => update(null)}>Start a new request</button></div>
    </SimplePanel>}
  </main>;
}
