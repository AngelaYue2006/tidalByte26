"use client";

import { useEffect, useRef, useState } from "react";
import { IconCheck, IconHierarchy, IconMessages, IconPlayerPause, IconPlayerPlay, IconPhone } from "@tabler/icons-react";
import { callStatus, clinics, demoEnd, script, stepLabels, timestamp } from "@/lib/callDemo";
import DecisionMap from "./DecisionMap";

type Props = {
  elapsed: number;
  paused?: boolean;
  budget?: number | null;
  togglePause?: () => void;
  back?: () => void;
};
export default function CallDemo({ elapsed, budget, paused = false, togglePause, back }: Props) {
  const [selected, select] = useState(0);
  const finished = elapsed >= demoEnd;
  const playing = !paused && !finished;
  const clinic = clinics[selected];
  const age = elapsed - clinic.delay;
  const turns = script(clinic, budget).filter(turn => turn.at <= age);
  const title = useRef<HTMLHeadingElement>(null);
  useEffect(() => { title.current?.focus({ preventScroll: true }); }, []);
  const transcript = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  useEffect(() => {
    follow.current = true;
  }, [selected]);
  useEffect(() => {
    if (follow.current && transcript.current) transcript.current.scrollTop = transcript.current.scrollHeight;
  }, [turns.length, selected]);

  return <div className="call-studio">
    <div className="studio-heading"><div><p className="eyebrow">Simulated session</p><h1 ref={title} tabIndex={-1}>{finished ? "Call review" : "Watch the agents"}</h1></div>
      {back && <button className="quiet-button" onClick={back}>Back to my request</button>}</div>
    <section aria-labelledby="session-title" className="demo-session">
      <div className="session-heading"><div>
        <h2 id="session-title">Dental cleaning</h2><p>{finished ? "Three clinics shared availability, pricing, and insurance details." : "Three agents are checking availability, pricing, and insurance."}</p></div>
        <div className="playback"><time>{timestamp(elapsed)}</time>
          {togglePause && !finished && <button onClick={togglePause}>{paused ? <IconPlayerPlay/> : <IconPlayerPause/>}{paused ? "Resume" : "Pause"}</button>}
        </div></div>
      <div className="clinic-picker" role="group" aria-label="Choose a clinic call">
        {clinics.map((item, i) => {
          const status = callStatus(elapsed - item.delay);
          return <button key={item.name} aria-pressed={selected === i} onClick={() => select(i)}>
            <span className="clinic-meta">Agent {String(i + 1).padStart(2, "0")}<span className={'clinic-status ' + status.toLowerCase()}>
              {status === "Calling" ? <i className={playing ? "signal moving" : "signal"} aria-hidden><b/><b/><b/></i> :
              status === "Finished" ? <IconCheck size={15}/> : <IconPhone size={14}/>} {status}</span></span>
            <strong>{item.name}</strong></button>;
        })}
      </div>
    </section>
    <div className="studio-grid">
      <section className="studio-panel"><header><IconHierarchy/><h2>Agent call graph</h2></header>
        <div className="graph-surface"><div className="graph-caption">Agent {String(selected + 1).padStart(2,"0")} · {clinic.name}</div>
        <DecisionMap key={clinic.name} animate={!finished} nodes={turns.flatMap(turn => turn.step ? [{ label: stepLabels[turn.step], text: turn.text }] : [])}/></div>
      </section>
      <section className="studio-panel"><header><IconMessages/><h2>Call transcript</h2></header>
        <div className="transcript-feed" ref={transcript} tabIndex={0} role="log" aria-label={clinic.name + " simulated transcript"}
          onScroll={e => { const el = e.currentTarget; follow.current = el.scrollHeight - el.clientHeight - el.scrollTop < 24; }}>
          {!turns.length && <p className="muted">Waiting for {clinic.name} to answer…</p>}
          {turns.map(turn => <article key={turn.at}><div><strong>{turn.speaker}</strong><time>{timestamp(turn.at + clinic.delay)}</time></div><p>{turn.text}</p></article>)}
        </div>
      </section>
    </div>
  </div>;
}
