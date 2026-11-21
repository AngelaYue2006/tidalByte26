"use client";

import { useSearchParams } from "next/navigation";
import SceneArt from "@/components/SceneArt";
import { viewerFromSearchParams } from "@/lib/viewer";

const EMBED_SRC = process.env.NEXT_PUBLIC_GOOGLE_CALENDAR_EMBED_SRC?.trim() ?? "";

/** Full Google Calendar embed, or a labelled empty state when env is unset. */
export default function CalendarPage() {
  const viewer = viewerFromSearchParams(useSearchParams());

  return (
    <main className="calendar-page">
      <header className="page-hero card page-hero-mint">
        <div className="page-hero-copy">
          <p className="page-kicker">Schedule</p>
          <h1 className="calendar-title">Calendar</h1>
          <p className="muted calendar-sub">
            Mary&apos;s appointments for {viewer.name}. Times in America/Chicago.
          </p>
        </div>
        <SceneArt name="calendar" className="scene-art page-hero-art" />
      </header>

      {EMBED_SRC ? (
        <div className="calendar-frame-wrap card">
          <iframe
            title="Google Calendar"
            src={EMBED_SRC}
            className="calendar-frame"
            loading="lazy"
            referrerPolicy="no-referrer-when-downgrade"
          />
        </div>
      ) : (
        <div className="card calendar-empty">
          <SceneArt name="care" className="scene-art scene-art-sm" />
          <p className="calendar-empty-title">Google Calendar embed not configured</p>
          <p className="muted">
            Add a public calendar embed URL to{" "}
            <code>NEXT_PUBLIC_GOOGLE_CALENDAR_EMBED_SRC</code> in <code>.env</code>, then restart{" "}
            <code>npm run dev</code>. Demo calendar only — make it public under Calendar settings →
            Access permissions → Integrate calendar.
          </p>
          <p className="faint calendar-empty-hint">
            Example:{" "}
            <code>
              https://calendar.google.com/calendar/embed?src=…&amp;ctz=America%2FChicago
            </code>
          </p>
        </div>
      )}
    </main>
  );
}
