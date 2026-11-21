"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";
import { IconCalendarCheck } from "@tabler/icons-react";
import { Suspense } from "react";
import DensityToggle from "@/components/DensityToggle";
import RolePicker from "@/components/RolePicker";
import { VIEWER_QUERY, hrefWithViewer, roleFromViewerId, VIEWERS } from "@/lib/viewer";

function NavLinks() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const viewerId = VIEWERS[roleFromViewerId(searchParams.get(VIEWER_QUERY))].viewerId;
  const search = searchParams.toString();

  const liveHref = hrefWithViewer("/", search, viewerId);
  const historyHref = hrefWithViewer("/history", search, viewerId);
  const calendarHref = hrefWithViewer("/calendar", search, viewerId);

  return (
    <nav className="header-links" aria-label="Primary">
      <Link
        href={liveHref}
        className="header-pill"
        aria-current={pathname === "/" ? "page" : undefined}
      >
        Live
      </Link>
      <Link
        href={historyHref}
        className="header-pill"
        aria-current={pathname === "/history" || pathname.startsWith("/history/") ? "page" : undefined}
      >
        History
      </Link>
      <Link
        href={calendarHref}
        className="header-pill"
        aria-current={pathname === "/calendar" ? "page" : undefined}
      >
        Calendar
      </Link>
    </nav>
  );
}

/** LifeLine header: brand, nav pills, density toggle, role picker. */
export default function Header() {
  return (
    <header className="site-header">
      <Link href="/" className="brand">
        <IconCalendarCheck aria-hidden stroke={1.75} />
        LifeLine
      </Link>
      <div className="header-nav">
        <Suspense fallback={<span className="faint">…</span>}>
          <NavLinks />
        </Suspense>
        <Suspense fallback={<span className="faint">…</span>}>
          <DensityToggle />
        </Suspense>
        <Suspense fallback={<span className="faint">Loading role…</span>}>
          <RolePicker />
        </Suspense>
      </div>
    </header>
  );
}
