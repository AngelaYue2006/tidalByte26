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

/** Loads one task + events; seeded fixtures when preview or API empty. */
export default function HistoryDetailPage({ taskId }: Props) {
  const viewer = viewerFromSearchParams(useSearchParams());
  const preview = useSearchParams().get("preview") === "1";
  const [task, setTask] = useState<HistoryTask | null>(null);
  const [events, setEvents] = useState<LiveEvent[]>([]);
  const [simulated, setSimulated] = useState(false);
  const [missing, setMissing] = useState(false);

  useEffect(() => {
    let cancelled = false;

    function applySeed() {
      const seed = SEEDED_TASKS.find((t) => t.id === taskId);
      if (!seed) {
        setMissing(true);
        return;
      }
      setTask(projectTaskForViewer(seed, viewer.role));
      setEvents(SEEDED_EVENTS[taskId] ?? []);
      setSimulated(true);
      setMissing(false);
    }

    async function load() {
      if (preview) {
        if (!cancelled) applySeed();
        return;
      }

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
      />
    </main>
  );
}

function isTaskShape(value: unknown): boolean {
  return Boolean(value && typeof value === "object" && "id" in value && "status" in value);
}
