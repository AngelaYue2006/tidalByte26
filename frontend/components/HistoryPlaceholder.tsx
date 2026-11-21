"use client";

import { useSearchParams } from "next/navigation";
import { tasksUrl } from "@/lib/api";
import { viewerFromSearchParams } from "@/lib/viewer";

/** Gate-0 history page: shows viewer_id on the tasks fetch path. */
export default function HistoryPlaceholder() {
  const viewer = viewerFromSearchParams(useSearchParams());
  const url = tasksUrl(viewer.viewerId);

  return (
    <main>
      <div className="card">
        <h1 className="placeholder-title">History</h1>
        <p className="placeholder-body">
          Past runs for <strong>{viewer.name}</strong>. The task list from{" "}
          <code>GET /api/tasks</code> lands in a later issue.
        </p>
        <p className="faint placeholder-meta">
          Fetches will use <code>{url}</code>
        </p>
      </div>
    </main>
  );
}
