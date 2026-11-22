"use client";

import WorkspaceLink from "./WorkspaceLink";
import { foldEvents } from "@/lib/dashboard";
import RecordedCallGraphs from "./RecordedCallGraphs";
import SceneArt from "@/components/SceneArt";
import type { LiveEvent } from "@/lib/events";
import type { HistoryTask } from "@/lib/history";
import { formatTaskDate, toneClass, toListItem } from "@/lib/history";

type Props = {
  task: HistoryTask;
  events: LiveEvent[];
  role: "owner" | "contact";
  simulated?: boolean;
};

export default function HistoryDetail({
  task,
  events,
  role,
  simulated,
}: Props) {
  const item = toListItem(task);
  const calls = role === "owner" ? foldEvents(events).calls : [];

  return (
    <div className="history-detail">
      <p className="history-back">
        <WorkspaceLink href="/history">Back to history</WorkspaceLink>
      </p>

      <header className="studio-heading"><h1>{role === "contact" ? "Mary’s appointment" : "Appointment details"}</h1></header>
      <div className="card history-detail-hero">
        <div>
          <div className="history-row-top">
            <time className="history-date">{formatTaskDate(task.created_at)}</time>
            <span className={toneClass(item.outcome.tone)}>{item.outcome.label}</span>
          </div>
          {role === "owner" && task.request_text ? (
            <p className="history-request">{task.request_text}</p>
          ) : null}
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

      {role === "owner" && <RecordedCallGraphs calls={calls}/>}
    </div>
  );
}
