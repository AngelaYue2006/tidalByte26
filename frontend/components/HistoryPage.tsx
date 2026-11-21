"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
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

/** Loads GET /api/tasks; falls back to two seeded runs when preview or API unavailable. */
export default function HistoryPage() {
  const viewer = viewerFromSearchParams(useSearchParams());
  const preview = useSearchParams().get("preview") === "1";
  const [tasks, setTasks] = useState<HistoryTask[] | null>(null);
  const [simulated, setSimulated] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;

    async function load() {
      if (preview) {
        if (!cancelled) {
          setTasks(sortNewestFirst(SEEDED_TASKS.map((t) => projectTaskForViewer(t, viewer.role))));
          setSimulated(true);
        }
        return;
      }

      try {
        const raw = await getTasks(viewer.viewerId);
        const parsed = sortNewestFirst(parseTasksPayload(raw)).map((t) =>
          projectTaskForViewer(t, viewer.role),
        );
        if (!cancelled) {
          if (parsed.length === 0) {
            // Backend stub or empty DB — show seeded runs so the page is demoable.
            setTasks(sortNewestFirst(SEEDED_TASKS.map((t) => projectTaskForViewer(t, viewer.role))));
            setSimulated(true);
          } else {
            setTasks(parsed);
            setSimulated(false);
          }
        }
      } catch (err) {
        if (!cancelled) {
          setTasks(sortNewestFirst(SEEDED_TASKS.map((t) => projectTaskForViewer(t, viewer.role))));
          setSimulated(true);
          setError(err instanceof Error ? err.message : "tasks unavailable");
        }
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [viewer.viewerId, viewer.role, preview]);

  if (tasks === null) {
    return (
      <main>
        <p className="muted">Loading history…</p>
      </main>
    );
  }

  return (
    <main>
      <h1 className="history-title">History</h1>
      <p className="muted history-sub">Past runs for {viewer.name}</p>
      {error && simulated ? (
        <p className="faint history-api-note">API unreachable — using seeded runs ({error})</p>
      ) : null}
      <HistoryList
        items={tasks.map(toListItem)}
        viewerId={viewer.viewerId}
        simulated={simulated}
      />
    </main>
  );
}
