"use client";

import { useSearchParams } from "next/navigation";
import { liveUrl } from "@/lib/live";
import { viewerFromSearchParams } from "@/lib/viewer";

/** Gate-0 live page: shows viewer_id wiring for SSE; event UI comes in later issues. */
export default function LivePlaceholder() {
  const viewer = viewerFromSearchParams(useSearchParams());
  const sse = liveUrl(viewer.viewerId);

  return (
    <main>
      <div className="card">
        <h1 className="placeholder-title">Live dashboard</h1>
        <p className="placeholder-body">
          Viewing as <strong>{viewer.name}</strong> ({viewer.role}). Request, calls, decision and
          confirmations land in later gate issues.
        </p>
        <p className="faint placeholder-meta">
          SSE will connect to <code>{sse}</code>
        </p>
      </div>
    </main>
  );
}
