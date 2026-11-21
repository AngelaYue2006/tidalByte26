"use client";

import { useEffect, useRef } from "react";
import { IconCheck } from "@tabler/icons-react";
import type { CallState } from "@/lib/dashboard";
import type { CallStatus } from "@/lib/events";

const STATUS_LABEL: Record<CallStatus, string> = {
  dialing: "Dialing…",
  live: "Live",
  hold: "On hold",
  done: "Done",
};

export type CallCardProps = {
  call: CallState;
  winner?: boolean;
};

/** One clinic call: name, meta, status, transcript, result. Winner gets the accent border. */
export default function CallCard({ call, winner = false }: CallCardProps) {
  const transcriptRef = useRef<HTMLDivElement>(null);
  const pulsing = call.status !== "done";

  useEffect(() => {
    const el = transcriptRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
  }, [call.transcripts]);

  return (
    <article
      className={`call-card${winner ? " call-card-winner" : ""}`}
      aria-label={`${call.clinic} call`}
    >
      <h3 className="call-card-title">
        <span>{call.clinic}</span>
        <span
          className={`call-status call-status-${call.status}${pulsing ? " pulse" : ""}`}
        >
          {call.status === "done" ? <IconCheck size={14} stroke={2} aria-hidden /> : null}
          {STATUS_LABEL[call.status]}
        </span>
      </h3>
      {call.meta ? <div className="faint call-card-meta">{call.meta}</div> : null}

      <div className="call-transcript" ref={transcriptRef} aria-live="polite">
        {call.transcripts.length === 0 ? (
          <div className="faint">Waiting for the call…</div>
        ) : (
          call.transcripts.map((line, i) => (
            <div className="call-line" key={`${call.call_id}-${i}-${line.text.slice(0, 24)}`}>
              <b>{line.speaker === "agent" ? "Agent" : "Clinic"}:</b> {line.text}
            </div>
          ))
        )}
      </div>

      <div className="call-result">
        <div>
          <small>Price</small>
          {call.result?.price ?? "—"}
        </div>
        <div>
          <small>Slot</small>
          {call.result ? (
            <span className={call.result.slotOk ? "good" : "bad"}>{call.result.slot}</span>
          ) : (
            "—"
          )}
        </div>
        <div>
          <small>Insurance</small>
          {call.result ? (
            <span className={call.result.insured ? "good" : "bad"}>
              {call.result.insured ? "Yes" : "No"}
            </span>
          ) : (
            "—"
          )}
        </div>
      </div>
    </article>
  );
}
