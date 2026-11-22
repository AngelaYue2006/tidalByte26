// Full Google Calendar embed for Mary's demo calendar.
import { Suspense } from "react";
import CalendarPage from "@/components/CalendarPage";

export default function CalendarRoute() {
  return (
    <Suspense fallback={<main><p className="muted">Loading…</p></main>}>
      <CalendarPage />
    </Suspense>
  );
}
