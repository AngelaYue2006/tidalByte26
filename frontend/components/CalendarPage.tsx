"use client";

import { workspaceMode } from "@/lib/workspace";

import { useState, useEffect } from "react";
import { demoArchive, readDemoRun } from "@/lib/callDemo";
import { useSearchParams } from "next/navigation";
import { viewerFromSearchParams } from "@/lib/viewer";

const EMBED_SRC = process.env.NEXT_PUBLIC_GOOGLE_CALENDAR_EMBED_SRC?.trim() ?? "";

/** Full Google Calendar embed, or a labelled empty state when env is unset. */
export default function CalendarPage() {
  const params = useSearchParams();
  const viewer = viewerFromSearchParams(params);

  const [showDemo, setShowDemo] = useState(false);
  useEffect(() => {
    setShowDemo(demoArchive() === "approved" || !!readDemoRun()?.approved);
  }, []);
  const hasDemo = workspaceMode(params) === "demo" && showDemo;

  return (
    <main className="calendar-page">
      <header className="studio-heading"><div><h1>{viewer.role === "contact" ? "Mary’s calendar" : "Calendar"}</h1>
        <p className="muted">Appointments for Mary Johnson. Times shown in Central time.</p></div></header>
      {hasDemo && <section className="card calendar-demo">
        <p className="eyebrow">Simulated appointment for Mary</p><h2>Dental cleaning</h2>
        <p><strong>Thursday, November 26 · 9:30 AM</strong></p><p>Bright Smile Dental · $95</p>
      </section>}
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
      ) : hasDemo ? null : (
        <div className="card calendar-empty">
          <h2 className="calendar-empty-title">No calendar connected</h2>
          <p className="muted">Appointments from Mary’s calendar will appear here once it is connected.</p>
        </div>
      )}
    </main>
  );
}
