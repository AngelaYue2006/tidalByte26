"use client";

import { useState } from "react";
import { contactOffer } from "@/lib/api";
import type { Viewer } from "@/lib/viewer";

export type ContactReplyProps = {
  viewer: Viewer;
  taskId?: string;
  /** Hide once a reply already exists. */
  hasReply?: boolean;
  /** Only show when a contact_request is open. */
  awaitingReply?: boolean;
};

function newKey(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return `offer-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Contact-only: I can drive / I can't → POST /api/contacts/offers. */
export default function ContactReply({
  viewer,
  taskId,
  hasReply = false,
  awaitingReply = false,
}: ContactReplyProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (viewer.role !== "contact" || !awaitingReply || hasReply) return null;

  async function send(canDrive: boolean) {
    if (!taskId || busy) return;
    setBusy(true);
    setError(null);
    try {
      await contactOffer(viewer.viewerId, {
        task_id: taskId,
        contact_id: viewer.viewerId,
        offer: canDrive
          ? { can_drive: true, pickup_time: "before the appointment" }
          : { can_drive: false },
        idempotency_key: newKey(),
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send reply");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card contact-reply" aria-label="Offer a ride">
      <h2 className="transport-title">Can you drive Mary?</h2>
      <p className="muted">Reply here or by SMS. Owner sees status only.</p>
      <div className="decision-actions">
        <button
          type="button"
          className="decision-approve"
          disabled={busy || !taskId}
          onClick={() => void send(true)}
        >
          I can drive
        </button>
        <button
          type="button"
          className="decision-reject"
          disabled={busy || !taskId}
          onClick={() => void send(false)}
        >
          I can&apos;t
        </button>
      </div>
      {error ? <p className="request-bar-error">{error}</p> : null}
    </section>
  );
}
