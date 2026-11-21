"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { HistoryListItem } from "@/lib/history";
import { toneClass } from "@/lib/history";

type Props = {
  items: HistoryListItem[];
  viewerId: string;
  simulated?: boolean;
};

/** Past runs newest first: date, chips, pick, price, outcome, ride. */
export default function HistoryList({ items, viewerId, simulated }: Props) {
  const preview = useSearchParams().get("preview");

  if (items.length === 0) {
    return (
      <div className="card">
        <p className="muted">No past runs yet.</p>
      </div>
    );
  }

  return (
    <ul className="history-list">
      {simulated ? (
        <li className="history-sim-banner muted">
          Showing two seeded past runs (preview). Live list comes from{" "}
          <code>GET /api/tasks</code> after demo reset.
        </li>
      ) : null}
      {items.map((item) => {
        const qs = new URLSearchParams({ viewer_id: viewerId });
        if (preview) qs.set("preview", preview);
        const href = `/history/${encodeURIComponent(item.id)}?${qs.toString()}`;
        return (
          <li key={item.id}>
            <Link href={href} className="history-row card">
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
            </Link>
          </li>
        );
      })}
    </ul>
  );
}
