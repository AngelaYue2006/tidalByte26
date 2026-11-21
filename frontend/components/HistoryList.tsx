"use client";

import WorkspaceLink from "./WorkspaceLink";
import SceneArt from "@/components/SceneArt";
import type { HistoryListItem } from "@/lib/history";
import { toneClass } from "@/lib/history";

type Props = {
  items: HistoryListItem[];
  simulated?: boolean;

};

/** Past runs newest first: date, chips, pick, price, outcome, ride. */
export default function HistoryList({ items, simulated }: Props) {
  if (items.length === 0) {
    return (
      <div className="card history-empty">
        <SceneArt name="calendar" className="scene-art scene-art-sm" />
        <p className="muted">No past appointments to show.</p>
      </div>
    );
  }

  return (
    <ul className="history-list">
      {simulated ? (
        <li className="history-sim-banner">
          Simulated appointment history
        </li>
      ) : null}
      {items.map((item, index) => {
        const href = `/history/${encodeURIComponent(item.id)}`;
        const art = index % 2 === 0 ? "care" : "phone";
        return (
          <li key={item.id}>
            <WorkspaceLink href={href} className="history-row card">
              <SceneArt name={art} className="history-row-art" alt="" />
              <div className="history-row-body">
                <div className="history-row-top">
                  <time className="history-date">{item.dateLabel}</time>
                  <span className={toneClass(item.outcome.tone)}>{item.outcome.label}</span>
                </div>
                <div className="history-row-meta">
                  <span>
                    <strong>{item.pick}</strong>
                    <span className="faint"> · {item.price}</span>
                  </span>
                  <span className={toneClass(item.ride.tone)}>{item.ride.label}</span>
                </div>
              </div>
            </WorkspaceLink>
          </li>
        );
      })}
    </ul>
  );
}
