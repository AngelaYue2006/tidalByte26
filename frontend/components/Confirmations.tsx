"use client";

import { IconCalendar, IconHeartHandshake, IconMessage } from "@tabler/icons-react";
import type { DashboardState } from "@/lib/dashboard";

export type ConfirmationsProps = {
  confirmations?: DashboardState["confirmations"];
  /** True once booked (or preview) so the three cards appear. */
  show?: boolean;
};

/** Three cards: text to owner, Google Calendar, text to contact. */
export default function Confirmations({ confirmations, show = false }: ConfirmationsProps) {
  const booked = confirmations?.booked;
  const notified = confirmations?.notified;
  if (!show && !booked && !notified) return null;

  const smsUser = booked?.sms_user;
  const calendar = booked?.calendar;
  const smsContact = notified?.sms_contact;
  const sendingUser = !smsUser;
  const sendingCal = !calendar;
  const sendingContact = !smsContact;

  return (
    <section className="confirms" aria-label="Confirmations">
      <article className="confirm-card">
        <h2>
          <IconMessage size={18} stroke={1.75} aria-hidden />
          Text to Mary
        </h2>
        <div className={sendingUser ? "muted pulse" : undefined}>
          {smsUser ?? "Sending…"}
        </div>
      </article>

      <article className="confirm-card">
        <h2>
          <IconCalendar size={18} stroke={1.75} aria-hidden />
          Google Calendar
        </h2>
        {calendar ? (
          <div dangerouslySetInnerHTML={{ __html: calendar }} />
        ) : (
          <div className={sendingCal ? "muted pulse" : "muted"}>Sending…</div>
        )}
      </article>

      <article className="confirm-card">
        <h2>
          <IconHeartHandshake size={18} stroke={1.75} aria-hidden />
          Text to Sarah (emergency contact)
        </h2>
        <div className={sendingContact ? "muted pulse" : undefined}>
          {smsContact ?? "Sending…"}
        </div>
      </article>
    </section>
  );
}
