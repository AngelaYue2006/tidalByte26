"use client";

import { useEffect, useState } from "react";
import WorkspaceLink from "./WorkspaceLink";
import { useSearchParams } from "next/navigation";
import CallDemo from "@/components/CallDemo";
import { archivedBudget, demoEnd } from "@/lib/callDemo";
import { viewerFromSearchParams } from "@/lib/viewer";

export default function DemoCallReview() {
  const viewer = viewerFromSearchParams(useSearchParams());
  const [budget, setBudget] = useState<number>();
  useEffect(() => setBudget(archivedBudget()), []);
  return <main><p><WorkspaceLink href="/history">Back to history</WorkspaceLink></p>
    {viewer.role === "owner" ? <CallDemo elapsed={demoEnd} budget={budget}/> : <section className="card"><h1>Mary’s appointment activity</h1><p>Three simulated clinics were contacted about a dental cleaning for Mary.</p><WorkspaceLink href="/calendar">View Mary’s calendar</WorkspaceLink></section>}
  </main>;
}
