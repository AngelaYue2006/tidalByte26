"use client";

import { workspaceMode } from "@/lib/workspace";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { IconActivityHeartbeat } from "@tabler/icons-react";
import RolePicker from "./RolePicker";
import WorkspaceLink from "./WorkspaceLink";
import { viewerFromSearchParams } from "@/lib/viewer";

export default function Header() {
  const pathname = usePathname();
  const params = useSearchParams();
  const router = useRouter();
  const mode = workspaceMode(params);
  const isOwner = viewerFromSearchParams(params).role === "owner";
  const links = [["/", "Activity"], ["/history", "History"], ["/calendar", "Calendar"], ...(isOwner ? [["/profile", "Profile"]] : [])];
  function switchMode(next: string) {
    const query = new URLSearchParams(params.toString());
    query.delete("preview");
    query.set("workspace", next);
    router.push(`/?${query}`);
  }
  return <header className="site-header">
    <WorkspaceLink href="/" className="brand"><IconActivityHeartbeat aria-hidden stroke={1.75}/>LifeLine</WorkspaceLink>
    <nav className="header-links" aria-label="Primary">
      {links.map(([path, label]) =>
        <WorkspaceLink key={path} href={path} className="header-pill"
          aria-current={pathname === path || pathname.startsWith(path + "/") ? "page" : undefined}>{label}</WorkspaceLink>)}
    </nav>
    <div className="header-settings">
      <label className="role-picker"><span>Mode</span><select aria-label="Dashboard mode" value={mode} onChange={e => switchMode(e.target.value)}>
        <option value="demo">Demo</option><option value="live">Live</option>{mode === "sample" && <option value="sample">Sample</option>}
      </select></label>
      <RolePicker/>
    </div>
  </header>;
}
