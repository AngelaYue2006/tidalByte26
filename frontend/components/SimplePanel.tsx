"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { IconCalendar, IconMessages, IconPhone } from "@tabler/icons-react";

export default function SimplePanel({ title, stage, demo, children }: {
  title: string; stage: "request" | "calls" | "appointment"; demo?: boolean; children: ReactNode;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => { heading.current?.focus({ preventScroll: true }); }, [title]);
  const Icon = { request: IconMessages, calls: IconPhone, appointment: IconCalendar }[stage];
  return <section className="simple-panel" key={title}>
    <div className="simple-symbol"><Icon aria-hidden size={30} stroke={1.6}/></div>
    <p className="eyebrow">{demo ? "Dental cleaning demo" : "Appointment assistant"}</p>
    <h1 tabIndex={-1} ref={heading}>{title}</h1>
    {children}
  </section>;
}
