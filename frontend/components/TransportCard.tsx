"use client";

import type { DashboardState } from "@/lib/dashboard";

export type TransportCardProps = {
  transport?: DashboardState["transport"];
  contact?: DashboardState["contact"];
  ride?: NonNullable<DashboardState["confirmations"]>["ride"];
};

/** Transport check (simulated), contact request/reply, ride confirmed. */
export default function TransportCard({ transport, contact, ride }: TransportCardProps) {
  if (!transport && !contact && !ride) return null;

  return (
    <section className="card transport-card" aria-label="Transport and contact">
      <h2 className="transport-title">Ride</h2>

      {transport ? (
        <div className="transport-status">
          {transport.status === "checking" ? (
            <p className="muted pulse">Checking…</p>
          ) : transport.status === "unavailable" ? (
            <p>
              No accessible ride found
              {transport.simulated ? (
                <span className="chip chip-warn transport-sim">simulated</span>
              ) : null}
            </p>
          ) : (
            <p className="good">Accessible ride available</p>
          )}
          {transport.reason && transport.status !== "checking" ? (
            <p className="faint transport-reason">{transport.reason}</p>
          ) : null}
        </div>
      ) : null}

      {contact?.message ? (
        <div className="transport-block">
          <h3 className="transport-sub">SMS to {contact.name ?? "contact"}</h3>
          <p className="transport-sms">{contact.message}</p>
        </div>
      ) : null}

      {contact?.reply ? (
        <div className="transport-block">
          <h3 className="transport-sub">Reply from {contact.name ?? "contact"}</h3>
          <p>{contact.reply.text}</p>
        </div>
      ) : null}

      {ride ? (
        <div className="transport-block transport-ride">
          <h3 className="transport-sub">Ride confirmed</h3>
          <p>
            <strong>{ride.driver}</strong> · pickup {ride.pickup_time}
          </p>
        </div>
      ) : null}
    </section>
  );
}
