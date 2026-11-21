"use client";

import { useState } from "react";
import { IconSparkles } from "@tabler/icons-react";
import { approve } from "@/lib/api";
import type { DashboardState } from "@/lib/dashboard";
import type { Viewer } from "@/lib/viewer";

export type DecisionCardProps = {
  viewer: Viewer;
  decision: NonNullable<DashboardState["decision"]>;
  approval?: DashboardState["approval"];
  taskId?: string;
  /** Simple (grandma) view: title + Approve only, no reason stack. */
  compact?: boolean;
};

function newKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `approve-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Why Nemotron picked X — reason chips, trade-off, owner-only Approve. */
export default function DecisionCard({
  viewer,
  decision,
  approval,
  taskId,
  compact = false,
}: DecisionCardProps) {
  const [busy, setBusy] = useState(false);
  const [sent, setSent] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const needsApproval = !!approval?.pick && !approval.approved;
  const showButtons = viewer.role === "owner" && needsApproval && !sent;
  const approved = approval?.approved;

  async function send(decisionValue: "approve" | "reject") {
    if (!taskId || busy || sent) return;
    setBusy(true);
    setError(null);
    try {
      await approve(taskId, viewer.viewerId, {
        actor_id: viewer.viewerId,
        decision: decisionValue,
        idempotency_key: newKey(),
      });
      setSent(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send approval");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={compact ? "card decision-card decision-compact" : "card decision-card"} aria-label="Decision">
      <h2 className="decision-title">
        <IconSparkles size={22} stroke={1.75} aria-hidden />
        <span>{decision.title}</span>
      </h2>

      {!compact ? (
        <>
          <div className="chips" aria-label="Reasons">
            {decision.reasons.map((r) => (
              <span key={r} className="chip chip-accent">
                {r}
              </span>
            ))}
            {decision.second.map((r) => (
              <span key={r} className="chip">
                {r}
              </span>
            ))}
          </div>

          <p className="muted decision-tradeoff">{decision.tradeoff}</p>
          <div className="faint decision-footer">
            Ranked by Nemotron 3 Super after hard-rule filtering (budget, free time, insurance).
          </div>
        </>
      ) : null}

      {needsApproval && approval?.pick ? (
        <div className="decision-pick faint">
          Pick: {approval.pick.clinic} · {approval.pick.slot} · {approval.pick.price}
          {approval.expires_at ? ` · expires ${approval.expires_at}` : ""}
        </div>
      ) : null}

      {showButtons ? (
        <div className="decision-actions">
          <button
            type="button"
            className="decision-approve"
            disabled={busy || !taskId}
            onClick={() => void send("approve")}
          >
            Approve
          </button>
          <button
            type="button"
            className="decision-reject"
            disabled={busy || !taskId}
            onClick={() => void send("reject")}
          >
            Not now
          </button>
        </div>
      ) : null}

      {approved ? (
        <p className="decision-approved">
          Approved by {approved.by} via {approved.via === "sms" ? "SMS" : "dashboard"}.
        </p>
      ) : null}

      {viewer.role === "contact" && needsApproval ? (
        <p className="faint decision-contact-note">Waiting for Mary to approve.</p>
      ) : null}

      {error ? <p className="request-bar-error">{error}</p> : null}
    </section>
  );
}
