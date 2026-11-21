"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import HistoryDetail from "@/components/HistoryDetail";
import { getEvents, getTask } from "@/lib/api";
import type { LiveEvent } from "@/lib/events";
import {
  parseEventsPayload,
  parseTasksPayload,
  projectTaskForViewer,
  type HistoryTask,
} from "@/lib/history";
import { SEEDED_EVENTS, SEEDED_TASKS } from "@/lib/history_fixtures";
import { viewerFromSearchParams } from "@/lib/viewer";

type Props = { taskId: string };

function seedFor(taskId: string, role: "owner" | "contact"): HistoryTask | null {
  const seed = SEEDED_TASKS.find((t) => t.id === taskId);
  return seed ? projectTaskForViewer(seed, role) : null;
}

/** Loads one task + events; seeded fixtures when preview, API empty, or seed id. */
export default function HistoryDetailPage({ taskId }: Props) {
  const searchParams = useSearchParams();
  const viewer = viewerFromSearchParams(searchParams);
  const preview = searchParams.get("preview") === "1";
  const density = searchParams.get("density");

  const initial = seedFor(taskId, viewer.role);
  const [task, setTask] = useState<HistoryTask | null>(initial);
  const [events, setEvents] = useState<LiveEvent[]>(() =>
    initial ? (SEEDED_EVENTS[taskId] ?? []) : [],
  );
  const [simulated, setSimulated] = useState(Boolean(initial));
  const [missing, setMissing] = useState(!initial && preview);

  useEffect(() => {
    let cancelled = false;

    function applySeed(): boolean {
      const seeded = seedFor(taskId, viewer.role);
      if (!seeded) {
        setMissing(true);
        setTask(null);
        return false;
      }
      setTask(seeded);
      setEvents(SEEDED_EVENTS[taskId] ?? []);
      setSimulated(true);
      setMissing(false);
      return true;
    }

    async function load() {
      // Always paint seed first when we have one so detail never flashes empty.
      applySeed();
      if (preview) return;

      try {
        const [taskRaw, eventsRaw] = await Promise.all([
          getTask(taskId, viewer.viewerId),
          getEvents(taskId, viewer.viewerId),
        ]);
        const tasks = parseTasksPayload(Array.isArray(taskRaw) ? taskRaw : [taskRaw]);
        const found = tasks[0] ?? (isTaskShape(taskRaw) ? (taskRaw as HistoryTask) : null);
        if (!found) {
          if (!cancelled) applySeed();
          return;
        }
        if (!cancelled) {
          setTask(projectTaskForViewer(found, viewer.role));
          setEvents(parseEventsPayload(eventsRaw));
          setSimulated(false);
          setMissing(false);
        }
      } catch {
        if (!cancelled) applySeed();
      }
    }

    void load();
    return () => {
      cancelled = true;
    };
  }, [taskId, viewer.viewerId, viewer.role, preview]);

  if (missing) {
    return (
      <main>
        <p className="muted">Task not found.</p>
      </main>
    );
  }

  if (!task) {
    return (
      <main>
        <p className="muted">Loading…</p>
      </main>
    );
  }

  return (
    <main>
      <HistoryDetail
        task={task}
        events={events}
        viewerId={viewer.viewerId}
        role={viewer.role}
        simulated={simulated}
        density={density}
      />
    </main>
  );
}

function isTaskShape(value: unknown): boolean {
  return Boolean(value && typeof value === "object" && "id" in value && "status" in value);
}
