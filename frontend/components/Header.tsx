"use client";

import { workspaceMode } from "@/lib/workspace";

import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { IconActivityHeartbeat } from "@tabler/icons-react";
import RolePicker from "./RolePicker";
import WorkspaceLink from "./WorkspaceLink";

export default function Header() {
  const pathname = usePathname();
  const params = useSearchParams();
  const router = useRouter();
  const mode = workspaceMode(params);
  function switchMode(next: string) {
    const query = new URLSearchParams(params.toString());
    query.delete("preview");
    query.set("workspace", next);
    router.push(`/?${query}`);
  }
  return <header className="site-header">
    <WorkspaceLink href="/" className="brand"><IconActivityHeartbeat aria-hidden stroke={1.75}/>LifeLine</WorkspaceLink>
    <nav className="header-links" aria-label="Primary">
      {[["/", "Activity"], ["/history", "History"], ["/calendar", "Calendar"]].map(([path, label]) =>
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
