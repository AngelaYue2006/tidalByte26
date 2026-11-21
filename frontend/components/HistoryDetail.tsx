"use client";

import Link from "next/link";
import SceneArt from "@/components/SceneArt";
import type { LiveEvent, TranscriptEvent } from "@/lib/events";
import type { HistoryTask } from "@/lib/history";
import { formatTaskDate, toneClass, toListItem } from "@/lib/history";

type Props = {
  task: HistoryTask;
  events: LiveEvent[];
  viewerId: string;
  role: "owner" | "contact";
  simulated?: boolean;
  density?: string | null;
};

function eventLabel(ev: LiveEvent): string {
  switch (ev.type) {
    case "request":
      return "Request";
    case "call_start":
      return `Call started · ${ev.clinic}`;
    case "call_status":
      return `Call ${ev.call_id} · ${ev.status}`;
    case "transcript":
      return `Transcript · ${ev.speaker}`;
    case "call_result":
      return `Offer · ${ev.price} · ${ev.slot}`;
    case "decision":
      return `Pick · ${ev.title}`;
    case "approval_required":
      return "Approval required";
    case "approved":
      return `Approved · ${ev.via}`;
    case "booked":
      return `Booked · ${ev.calendar}`;
    case "transport_check":
      return `Transport · ${ev.status}`;
    case "contact_request":
      return "Contact asked";
    case "contact_reply":
      return "Contact replied";
    case "ride_confirmed":
      return `Ride · ${ev.driver}`;
    case "notified":
      return "Notified";
    case "task_updated":
      return `Status · ${ev.status}`;
    default:
      return ev.type;
  }
}

function transcriptsByCall(events: LiveEvent[]): Map<string, TranscriptEvent[]> {
  const map = new Map<string, TranscriptEvent[]>();
  for (const ev of events) {
    if (ev.type !== "transcript") continue;
    const list = map.get(ev.call_id) ?? [];
    list.push(ev);
    map.set(ev.call_id, list);
  }
  return map;
}

/** Detail: summary, event trail, and (owner) call transcripts. */
export default function HistoryDetail({
  task,
  events,
  viewerId,
  role,
  simulated,
  density,
}: Props) {
  const item = toListItem(task);
  const backQs = new URLSearchParams({ viewer_id: viewerId });
  if (simulated) backQs.set("preview", "1");
  if (density) backQs.set("density", density);
  const back = `/history?${backQs.toString()}`;
  const transcripts = role === "owner" ? transcriptsByCall(events) : new Map();

  return (
    <div className="history-detail">
      <p className="history-back">
        <Link href={back}>← History</Link>
      </p>

      <div className="card history-detail-hero page-hero-coral">
        <div>
          <div className="history-row-top">
            <time className="history-date">{formatTaskDate(task.created_at)}</time>
            <span className={toneClass(item.outcome.tone)}>{item.outcome.label}</span>
          </div>
          {role === "owner" && task.request_text ? (
            <p className="history-request">{task.request_text}</p>
          ) : null}
          <div className="chips history-chips">
            {item.chips
              .filter((c) => !c.startsWith("!"))
              .map((c) => (
                <span key={c} className="chip">
                  {c}
                </span>
              ))}
          </div>
          <div className="history-row-meta">
            <span>
              <strong>{item.pick}</strong>
              <span className="faint"> · {item.price}</span>
            </span>
            <span className={toneClass(item.ride.tone)}>{item.ride.label}</span>
          </div>
          {simulated ? (
            <p className="faint history-sim-note">Simulated seeded run</p>
          ) : null}
        </div>
        <SceneArt name="care" className="scene-art scene-art-sm" />
      </div>

      <section className="card">
        <h2 className="history-section-title">Event trail</h2>
        <ol className="history-trail">
          {events
            .filter((ev) => ev.type !== "heartbeat" && ev.type !== "snapshot")
            .map((ev, i) => (
              <li key={`${ev.type}-${i}`} className="history-trail-item">
                <span className="history-trail-label">{eventLabel(ev)}</span>
                {ev.type === "decision" ? (
                  <p className="muted history-trail-body">{ev.tradeoff}</p>
                ) : null}
                {ev.type === "transcript" && role === "owner" ? (
                  <p className="muted history-trail-body">
                    <b>{ev.speaker === "agent" ? "AI" : "Clinic"}:</b> {ev.text}
                  </p>
                ) : null}
              </li>
            ))}
        </ol>
      </section>

      {role === "owner" && transcripts.size > 0 ? (
        <section className="card">
          <h2 className="history-section-title">Call transcripts</h2>
          {[...transcripts.entries()].map(([callId, lines]) => (
            <div key={callId} className="history-transcript-block">
              <h3 className="history-call-title">Call {callId}</h3>
              <div className="call-transcript history-transcript">
                {lines.map((line: TranscriptEvent, i: number) => (
                  <div key={i} className="call-line">
                    <b>{line.speaker === "agent" ? "AI" : "Clinic"}:</b> {line.text}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </section>
      ) : null}
    </div>
  );
}
