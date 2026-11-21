"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import HistoryList from "@/components/HistoryList";
import SceneArt from "@/components/SceneArt";
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

/** Loads GET /api/tasks; always shows seeded runs when API is empty or down. */
export default function HistoryPage() {
  const searchParams = useSearchParams();
  const viewer = viewerFromSearchParams(searchParams);
  const preview = searchParams.get("preview");
  const density = searchParams.get("density");
  const forcePreview = preview === "1";

  // Paint seeds immediately so /history never looks broken while fetch runs.
  const [tasks, setTasks] = useState<HistoryTask[]>(() => seedTasks(viewer.role));
  const [simulated, setSimulated] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setTasks(seedTasks(viewer.role));
    setSimulated(true);

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
        if (parsed.length === 0) {
          setTasks(seedTasks(viewer.role));
          setSimulated(true);
          setError(null);
        } else {
          setTasks(parsed);
          setSimulated(false);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          setTasks(seedTasks(viewer.role));
          setSimulated(true);
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
      <header className="page-hero card page-hero-coral">
        <div className="page-hero-copy">
          <p className="page-kicker">Past runs</p>
          <h1 className="history-title">History</h1>
          <p className="muted history-sub">
            Everything LifeLine booked for {viewer.name} — tap a run for the full trail.
          </p>
          {error && simulated ? (
            <p className="faint history-api-note">API unreachable — showing demo runs ({error})</p>
          ) : null}
        </div>
        <SceneArt name="family" className="scene-art page-hero-art" />
      </header>
      <HistoryList
        items={tasks.map(toListItem)}
        viewerId={viewer.viewerId}
        simulated={simulated}
        preview={preview}
        density={density}
      />
    </main>
  );
}
