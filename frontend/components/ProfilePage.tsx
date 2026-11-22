"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { getUser, type UserProfile } from "@/lib/api";
import { viewerFromSearchParams } from "@/lib/viewer";

const SHARED_LABELS: Record<string, string> = {
  care_type: "Care type",
  budget_max: "Budget cap",
  insurance_carrier: "Insurance carrier name",
  time_range: "Free time windows",
  needs_ride: "Needs a ride",
  search_area: "Search area",
};

function formatDob(dob: string | null): string {
  if (!dob) return "—";
  const d = new Date(`${dob}T12:00:00`);
  return Number.isNaN(d.getTime()) ? dob : d.toLocaleDateString("en-US", { year: "numeric", month: "long", day: "numeric" });
}

/** Read-only view of the owner's record. The contact role never reaches this page: the header hides the pill and the
 *  backend answers 404 for a contact viewer, so the page only shows the scope message. */
export default function ProfilePage() {
  const params = useSearchParams();
  const viewer = viewerFromSearchParams(params);
  const [user, setUser] = useState<UserProfile | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (viewer.role !== "owner") return;
    let cancelled = false;
    getUser(viewer.viewerId)
      .then((u) => { if (!cancelled) setUser(u); })
      .catch((e: Error) => { if (!cancelled) setError(e.message || "Could not load the profile."); });
    return () => { cancelled = true; };
  }, [viewer.role, viewer.viewerId]);

  if (viewer.role !== "owner") {
    return (
      <main className="profile-page">
        <header className="studio-heading"><div><h1>Profile</h1>
          <p className="muted">Only Mary can see her own record. You receive the clinic, time, address and the ride need when a booking needs you.</p></div></header>
      </main>
    );
  }

  return (
    <main className="profile-page">
      <header className="studio-heading"><div><h1>Profile</h1>
        <p className="muted">Your record stays on this device. Clinics and cloud models never receive it.</p></div></header>

      {error && <p className="muted" role="alert">{error}</p>}

      <section className="card profile-card" aria-busy={!user && !error}>
        <p className="eyebrow">Kept on this device <span className="chip chip-good">Never sent</span></p>
        <dl className="profile-grid">
          <div><dt>Name</dt><dd>{user?.name ?? "…"}</dd></div>
          <div><dt>Date of birth</dt><dd>{user ? formatDob(user.dob) : "…"}</dd></div>
          <div><dt>Home address</dt><dd>{user?.home_address ?? "…"}</dd></div>
          <div><dt>Phone</dt><dd>{user?.phone_e164 ?? "…"}</dd></div>
          <div><dt>Insurance</dt><dd>{user ? (user.insurance?.carrier ?? "None on file") : "…"}</dd></div>
          <div><dt>Member ID</dt><dd>{user ? (user.insurance?.member_id_masked ?? "—") : "…"}</dd></div>
          <div><dt>Time zone</dt><dd>{user?.timezone ?? "…"}</dd></div>
        </dl>
      </section>

      <section className="card profile-card">
        <p className="eyebrow">What a clinic may hear</p>
        <p className="muted">When you make a request, the on-device model keeps only these facts and drops the rest before any call starts.</p>
        <ul className="profile-shared">
          {(user?.shared_fields ?? Object.keys(SHARED_LABELS)).map((f) => <li key={f}>{SHARED_LABELS[f] ?? f}</li>)}
        </ul>
        <p className="muted">Never shared: date of birth, home address, member ID, phone number, symptoms, medications or mobility details.</p>
      </section>
    </main>
  );
}
