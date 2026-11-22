"use client";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import type { Density } from "@/lib/density";
import { densityFromSearchParams, hrefWithDensity } from "@/lib/density";
import { viewerFromSearchParams } from "@/lib/viewer";

/** Animated Simple ↔ Detailed control; writes ?density= into the URL. */
export default function DensityToggle() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const viewer = viewerFromSearchParams(searchParams);
  const density = densityFromSearchParams(searchParams, viewer.role);
  const search = searchParams.toString();

  function setDensity(next: Density) {
    router.replace(hrefWithDensity(pathname, search, next));
  }

  return (
    <div
      className="density-toggle"
      role="group"
      aria-label="View density"
      data-density={density}
    >
      <span className="density-toggle-thumb" aria-hidden />
      <button
        type="button"
        className={density === "simple" ? "density-toggle-btn is-active" : "density-toggle-btn"}
        aria-pressed={density === "simple"}
        onClick={() => setDensity("simple")}
      >
        Simple
      </button>
      <button
        type="button"
        className={density === "detailed" ? "density-toggle-btn is-active" : "density-toggle-btn"}
        aria-pressed={density === "detailed"}
        onClick={() => setDensity("detailed")}
      >
        Detailed
      </button>
    </div>
  );
}
