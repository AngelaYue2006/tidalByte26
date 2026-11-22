"use client";

import { workspaceMode } from "@/lib/workspace";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import WorkspaceLink from "./WorkspaceLink";
import { demoArchive, readDemoRun, elapsedSeconds, demoEnd } from "@/lib/callDemo";
import HistoryList from "@/components/HistoryList";
import { getTasks } from "@/lib/api";
import {
  parseTasksPayload,
  projectTaskForViewer,
  sortNewestFirst,
  toListItem,
  type HistoryTask,
} from "@/lib/history";
import { SEEDED_TASKS } from "@/lib/history_fixtures";
import { viewerFromSearchParams } from "@/lib/viewer";

function seedTasks(role: "owner" | "contact"): HistoryTask[] {
  return sortNewestFirst(SEEDED_TASKS.map((t) => projectTaskForViewer(t, role)));
}

/** Demo history is local. Live history is scoped to the selected viewer. */
export default function HistoryPage() {
  const searchParams = useSearchParams();
  const viewer = viewerFromSearchParams(searchParams);

  const [demoComplete, setDemoComplete] = useState(false);
  useEffect(() => {
    const run = readDemoRun();
    setDemoComplete(Boolean(demoArchive()) || (!!run && elapsedSeconds(run) >= demoEnd));
  }, []);
  const forcePreview = workspaceMode(searchParams) !== "live";

  // Paint seeds immediately so /history never looks broken while fetch runs.
  const [tasks, setTasks] = useState<HistoryTask[]>(() => forcePreview ? seedTasks(viewer.role) : []);
  const [simulated, setSimulated] = useState(forcePreview);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setTasks(forcePreview ? seedTasks(viewer.role) : []);
    setSimulated(forcePreview);

    async function load() {
      if (forcePreview) {
        if (!cancelled) {
          setError(null);
        }
        return;
      }

      try {
        const raw = await getTasks(viewer.viewerId);
        const parsed = sortNewestFirst(parseTasksPayload(raw)).map((t) =>
          projectTaskForViewer(t, viewer.role),
        );
        if (cancelled) return;
        setTasks(parsed);
        setSimulated(false);
        setError(null);
      } catch (err) {
        if (!cancelled) {
          setTasks([]);
          setSimulated(false);
          setError(err instanceof Error ? err.message : "tasks unavailable");
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [viewer.viewerId, viewer.role, forcePreview]);

  return (
    <main className="history-page">
      <header className="studio-heading"><div><h1>{viewer.role === "contact" ? "Mary’s history" : "History"}</h1>
        <p className="muted">Past appointment requests for Mary Johnson.</p></div></header>
      {error && !forcePreview && <p role="status">Appointment history is unavailable right now.</p>}
      {forcePreview && demoComplete && <WorkspaceLink className="demo-history-link card" href="/history/demo-cleaning">
        <strong>Dental cleaning for Mary</strong><span>{viewer.role === "owner" ? "Review simulated calls" : "View simulated appointment activity"}</span>
      </WorkspaceLink>}
      {!error && <HistoryList
        items={tasks.map(toListItem)}
        simulated={simulated}
      />}
    </main>
  );
}
