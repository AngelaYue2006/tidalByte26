"use client";

import type { CallState } from "@/lib/dashboard";

type Props = {
  calls: CallState[];
  winnerId?: string;
};

const STATUS_LABEL: Record<CallState["status"], string> = {
  dialing: "Dialing…",
  live: "Live",
  hold: "On hold",
  done: "Done",
};

/** Compact clinic call status for the simple (grandma) live view. */
export default function CallStrip({ calls, winnerId }: Props) {
  if (calls.length === 0) return null;

  const anyLive = calls.some((c) => c.status === "live" || c.status === "dialing" || c.status === "hold");

  return (
    <section className="card call-strip" aria-label="Clinic calls">
      <h2 className="call-strip-title">
        {anyLive ? "AIGranni is calling clinics…" : "Clinic calls"}
      </h2>
      <ul className="call-strip-list">
        {calls.map((call) => {
          const winner = winnerId === call.call_id;
          return (
            <li
              key={call.call_id}
              className={winner ? "call-strip-item is-winner" : "call-strip-item"}
            >
              <span className="call-strip-clinic">{call.clinic}</span>
              <span className={`call-status call-status-${call.status}`}>
                {STATUS_LABEL[call.status]}
              </span>
              {call.result ? (
                <span className="call-strip-result faint">
                  {call.result.slot} · {call.result.price}
                </span>
              ) : null}
            </li>
          );
        })}
      </ul>
    </section>
  );
}
