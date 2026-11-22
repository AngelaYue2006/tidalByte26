"use client";

import { useEffect, useRef, useState } from "react";
import { IconMessage, IconPhone } from "@tabler/icons-react";

export type GraphNode = { label: string; text: string; clinic?: boolean };

export default function DecisionMap({ nodes, animate = false }: { nodes: GraphNode[]; animate?: boolean }) {
  const surface = useRef<HTMLDivElement>(null);
  const [columns, setColumns] = useState(3);
  const [selected, setSelected] = useState<number | null>(null);
  useEffect(() => {
    if (!surface.current) return;
    const observer = new ResizeObserver(([entry]) => {
      setColumns(Math.max(2, Math.min(4, Math.floor(entry.contentRect.width / 155))));
    });
    observer.observe(surface.current);
    return () => observer.disconnect();
  }, []);
  function point(index: number) {
    const row = Math.floor(index / columns);
    const col = index % columns;
    return { x: 76 + (row % 2 ? columns - col - 1 : col) * 152, y: 39 + row * 104 };
  }
  const active = selected !== null && selected < nodes.length ? selected : nodes.length - 1;
  return <div ref={surface} className="growing-map">
    {nodes.length ? <>
      <svg viewBox={`0 0 ${columns * 152} ${Math.ceil(nodes.length / columns) * 104}`} aria-label="Call graph in conversation order" role="group">
        {nodes.map((node, index) => {
          const { x, y } = point(index);
          const prev = point(Math.max(0, index - 1));
          const vertical = prev.x === x;
          const direction = x > prev.x ? 1 : -1;
          const bend = x < 100 ? -51 : 51;
          const path = vertical
            ? `M${x+bend/3} ${prev.y+12} C${x+bend} ${prev.y+20} ${x+bend} ${y-25} ${x+bend/3} ${y-12}`
            : `M${prev.x+20*direction} ${y} H${x-20*direction}`;
          const Icon = node.clinic ? IconMessage : IconPhone;
          return <g key={index}>
            {index > 0 && <path d={path} pathLength="1" className={animate ? "grow-edge animated" : "grow-edge"}/>}
            <g className={index === active ? "node current" : "node visited"} transform={`translate(${x} ${y})`}
              role="button" tabIndex={0} aria-pressed={index === active} aria-label={`${index+1}. ${node.label}. ${node.text}`}
              onClick={() => setSelected(index)} onKeyDown={e => {
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSelected(index); }
              }}>
              <circle r="19"/><Icon x="-10" y="-10" width="20" height="20" aria-hidden/>
              <text y="39" textAnchor="middle">{node.label}</text>
            </g>
          </g>;
        })}
      </svg>
      <div className="graph-detail"><strong>{nodes[active].label}</strong><p>{nodes[active].text}</p>
        {animate && active < nodes.length - 1 && <button onClick={() => setSelected(null)}>Follow latest step</button>}
      </div>
    </> : <p className="map-empty">Waiting for the first call event…</p>}
  </div>;
}
