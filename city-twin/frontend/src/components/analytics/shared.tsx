import type { ReactNode } from "react";

export function StatCard({
  label,
  value,
  unit,
  sub,
  color,
}: {
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5 px-3 py-2 bg-bg-tertiary border border-border-subtle">
      <span className="font-mono text-[9px] text-text-muted uppercase tracking-widest">
        {label}
      </span>
      <span className={`font-mono text-lg font-bold tabular-nums leading-none ${color ?? "text-text-primary"}`}>
        {value}
        {unit && <span className="text-[11px] text-text-muted ml-1 font-normal">{unit}</span>}
      </span>
      {sub && <span className="font-mono text-[9px] text-text-secondary leading-tight">{sub}</span>}
    </div>
  );
}

export function Metric({
  label,
  value,
  unit,
  color,
}: {
  label: string;
  value: string;
  unit?: string;
  color?: string;
}) {
  return (
    <div className="flex flex-col px-3 py-2">
      <span className="font-mono text-[9px] text-text-muted uppercase tracking-wider">{label}</span>
      <span className={`font-mono text-[15px] font-bold tabular-nums leading-tight ${color ?? "text-text-primary"}`}>
        {value}
        {unit && <span className="text-[10px] text-text-muted ml-0.5 font-normal">{unit}</span>}
      </span>
    </div>
  );
}

export function ChartFrame({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="border border-border-subtle bg-bg-tertiary">
      <div className="px-3 py-1.5 border-b border-border-subtle">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">{title}</span>
      </div>
      <div className="p-2">{children}</div>
    </div>
  );
}

export function Legend({ items }: { items: [string, string][] }) {
  return (
    <div className="flex flex-wrap gap-3 px-2 pb-1">
      {items.map(([color, label]) => (
        <span key={label} className="flex items-center gap-1.5 font-mono text-[9px] text-text-secondary">
          <span className="inline-block w-2.5 h-[2px]" style={{ background: color }} />
          {label}
        </span>
      ))}
    </div>
  );
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export function TimeTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-bg-elevated border border-border-strong px-2 py-1 font-mono text-[10px]">
      <div className="text-text-muted">t = {Number(label).toFixed(2)} s</div>
      {/* eslint-disable-next-line @typescript-eslint/no-explicit-any */}
      {payload.map((p: any) => (
        <div key={p.dataKey} style={{ color: p.color }}>
          {p.name}: {Number(p.value).toExponential(2)}
        </div>
      ))}
    </div>
  );
}

export function LoadingNote({ text = "running…" }: { text?: string }) {
  return <span className="font-mono text-[10px] text-accent-yellow animate-pulse">{text}</span>;
}
