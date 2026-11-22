"use client";

import { useEffect } from "react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import {
  VIEWERS,
  VIEWER_QUERY,
  hrefWithViewer,
  roleFromViewerId,
  type Role,
} from "@/lib/viewer";

/** Owner / contact picker. Writes viewer_id into the URL for every fetch and SSE. */
export default function RolePicker() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const role = roleFromViewerId(searchParams.get(VIEWER_QUERY));
  const viewer = VIEWERS[role];

  useEffect(() => {
    if (searchParams.get(VIEWER_QUERY)) return;
    router.replace(hrefWithViewer(pathname, searchParams.toString(), viewer.viewerId));
  }, [pathname, router, searchParams, viewer.viewerId]);

  function onChange(next: Role) {
    const href = hrefWithViewer(pathname, searchParams.toString(), VIEWERS[next].viewerId);
    router.replace(href);
  }

  return (
    <label className="role-picker">
      <span>Viewing as</span>
      <select
        aria-label="Dashboard role"
        value={role}
        onChange={(e) => onChange(e.target.value as Role)}
      >
        <option value="owner">{VIEWERS.owner.label}</option>
        <option value="contact">{VIEWERS.contact.label}</option>
      </select>
    </label>
  );
}
