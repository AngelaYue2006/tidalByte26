"use client";

import { useState } from "react";
import type { CallState } from "@/lib/dashboard";
import DecisionMap from "./DecisionMap";

export default function RecordedCallGraphs({ calls, animate = false }: { calls: CallState[]; animate?: boolean }) {
  const [selected, setSelected] = useState("");
  const call = calls.find(item => item.call_id === selected) ?? calls[0];
  if (!call) return <p className="muted">No call events are available yet.</p>;
  return <section className="studio-panel">
    <header><h2>Agent call graph</h2></header>
    <div className="recorded-picker" role="group" aria-label="Choose a clinic">
      {calls.map(item => <button key={item.call_id} aria-pressed={item.call_id === call.call_id} onClick={() => setSelected(item.call_id)}>
        {item.clinic}</button>)}
    </div>
    <div className="graph-surface"><DecisionMap key={call.call_id} nodes={call.graph ?? []} animate={animate}/></div>
  </section>;
}
