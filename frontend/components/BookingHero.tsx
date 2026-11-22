"use client";

import type { DashboardState } from "@/lib/dashboard";

type Props = {
  decision?: DashboardState["decision"];
  approval?: DashboardState["approval"];
  confirmations?: DashboardState["confirmations"];
};

/** Large booked / pick time block for the simple live view. */
export default function BookingHero({ decision, approval, confirmations }: Props) {
  const booked = confirmations?.booked;
  const pick = approval?.pick;

  if (!booked && !pick && !decision) return null;

  const title = booked
    ? booked.tentative
      ? "Tentative appointment"
      : "You're booked"
    : pick
      ? "Suggested time"
      : "LifeLine's pick";

  const line = booked
    ? booked.calendar.replace(/<[^>]+>/g, " ").replace(/\s+/g, " ").trim()
    : pick
      ? `${pick.clinic} · ${pick.slot} · ${pick.price}`
      : decision?.title ?? "";

  return (
    <section className="card booking-hero" aria-label="Appointment time">
      <p className="booking-hero-label">{title}</p>
      <p className="booking-hero-time">{line}</p>
      {confirmations?.ride ? (
        <p className="booking-hero-ride muted">
          Ride with {confirmations.ride.driver} · {confirmations.ride.pickup_time}
        </p>
      ) : null}
    </section>
  );
}
