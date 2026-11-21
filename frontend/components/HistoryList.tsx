"use client";

import Link from "next/link";
import SceneArt from "@/components/SceneArt";
import type { HistoryListItem } from "@/lib/history";
import { toneClass } from "@/lib/history";

type Props = {
  items: HistoryListItem[];
  viewerId: string;
  simulated?: boolean;
  /** Preserve preview= when linking to detail. */
  preview?: string | null;
  density?: string | null;
};

/** Past runs newest first: date, chips, pick, price, outcome, ride. */
export default function HistoryList({ items, viewerId, simulated, preview, density }: Props) {
  if (items.length === 0) {
    return (
      <div className="card history-empty">
        <SceneArt name="calendar" className="scene-art scene-art-sm" />
        <p className="muted">No past runs yet. Finish a Live booking and it will show up here.</p>
      </div>
    );
  }

  return (
    <ul className="history-list">
      {simulated ? (
        <li className="history-sim-banner">
          Demo history — two seeded past runs. Live data appears after{" "}
          <code>POST /api/demo/reset</code> when the tasks API is up.
        </li>
      ) : null}
      {items.map((item, index) => {
        const qs = new URLSearchParams({ viewer_id: viewerId });
        if (preview) qs.set("preview", preview);
        if (density) qs.set("density", density);
        const href = `/history/${encodeURIComponent(item.id)}?${qs.toString()}`;
        const art = index % 2 === 0 ? "care" : "phone";
        return (
          <li key={item.id}>
            <Link href={href} className="history-row card">
              <SceneArt name={art} className="history-row-art" alt="" />
              <div className="history-row-body">
                <div className="history-row-top">
                  <time className="history-date">{item.dateLabel}</time>
                  <span className={toneClass(item.outcome.tone)}>{item.outcome.label}</span>
                </div>
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
              </div>
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
