"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { ComponentProps } from "react";
import { hrefWithViewer, viewerFromSearchParams } from "@/lib/viewer";

export default function WorkspaceLink({ href, ...props }: Omit<ComponentProps<typeof Link>, "href"> & { href: string }) {
  const params = useSearchParams();
  return <Link {...props} href={hrefWithViewer(href, params.toString(), viewerFromSearchParams(params).viewerId)}/>;
}
