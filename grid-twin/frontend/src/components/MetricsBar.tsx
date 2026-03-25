import type { GridState } from "../types/grid";

interface Props {
  gridState: GridState | null;
}

function freqColorClass(hz: number): string {
  const dev = Math.abs(hz - 60.0);
  if (dev > 1.0) return "text-accent-red";
  if (dev > 0.5) return "text-accent-yellow";
  return "text-accent-green";
}

function formatSimTime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

interface MetricProps {
  value: string;
  label: string;
  colorClass?: string;
}

function Metric({ value, label, colorClass = "text-text-primary" }: MetricProps) {
  return (
    <div className="flex flex-col items-center justify-center p-2">
      <span className={`font-mono text-lg font-semibold ${colorClass}`}>
        {value}
      </span>
      <span className="font-mono text-[9px] text-text-muted uppercase tracking-wider">
        {label}
      </span>
    </div>
  );
}

export default function MetricsBar({ gridState }: Props) {
  const freq = gridState?.system_frequency_hz ?? 60.0;
  const gen = gridState?.total_generation_mw ?? 0;
  const load = gridState?.total_load_mw ?? 0;
  const surplus = gen - load;
  const alertCount = gridState?.active_alerts?.length ?? 0;
  const critAlerts = gridState?.active_alerts?.filter(
    (a) => a.severity === "CRITICAL" || a.severity === "WARNING"
  ).length ?? 0;
  const simTime = gridState?.sim_time_s ?? 0;

  return (
    <div className="grid grid-cols-3 grid-rows-2 border-b border-border-subtle bg-bg-secondary">
      <Metric
        value={`${freq.toFixed(2)} Hz`}
        label="Frequency"
        colorClass={freqColorClass(freq)}
      />
      <Metric value={`${gen.toFixed(1)} MW`} label="Generation" />
      <Metric value={`${load.toFixed(1)} MW`} label="Load" />
      <Metric
        value={`${surplus >= 0 ? "+" : ""}${surplus.toFixed(1)} MW`}
        label="Surplus"
        colorClass={surplus < 0 ? "text-accent-red" : "text-accent-green"}
      />
      <Metric
        value={`${critAlerts} ALERTS`}
        label="Active"
        colorClass={critAlerts > 0 ? "text-accent-yellow" : "text-text-secondary"}
      />
      <Metric value={formatSimTime(simTime)} label="Sim Time" />
    </div>
  );
}
