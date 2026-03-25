import type { GridState } from "../types/grid";

interface Props {
  gridState: GridState | null;
}

function freqColor(hz: number): string {
  const dev = Math.abs(hz - 60.0);
  if (dev > 1.0) return "text-accent-red";
  if (dev > 0.5) return "text-accent-yellow";
  return "text-accent-green";
}

function surplusColor(mw: number): string {
  if (mw < -20) return "text-accent-red";
  if (mw < 0) return "text-accent-yellow";
  return "text-accent-green";
}

function formatSimTime(s: number): string {
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  const sec = Math.floor(s % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`;
}

interface MetricCellProps {
  value: string;
  label: string;
  sub?: string;
  colorClass?: string;
}

function MetricCell({
  value,
  label,
  sub,
  colorClass = "text-text-primary",
}: MetricCellProps) {
  return (
    <div className="flex flex-col items-center justify-center p-2 min-w-0">
      <span className={`font-mono text-lg font-semibold leading-none ${colorClass}`}>
        {value}
      </span>
      <span className="font-mono text-[9px] text-text-muted uppercase tracking-wider mt-0.5">
        {label}
      </span>
      {sub && (
        <span className="font-mono text-[8px] text-text-muted mt-0.5">
          {sub}
        </span>
      )}
    </div>
  );
}

export default function MetricsBar({ gridState }: Props) {
  const freq = gridState?.system_frequency_hz ?? 60.0;
  const gen = gridState?.total_generation_mw ?? 0;
  const load = gridState?.total_load_mw ?? 0;
  const loss = gridState?.total_loss_mw ?? 0;
  const surplus = gen - load;
  const alertCount =
    gridState?.active_alerts?.filter(
      (a) => a.severity === "CRITICAL" || a.severity === "WARNING"
    ).length ?? 0;
  const simTime = gridState?.sim_time_s ?? 0;

  return (
    <div className="grid grid-cols-3 grid-rows-2 border-b border-border-subtle bg-bg-secondary">
      <MetricCell
        value={`${freq.toFixed(2)} Hz`}
        label="Frequency"
        colorClass={freqColor(freq)}
      />
      <MetricCell
        value={`${gen.toFixed(1)} MW`}
        label="Generation"
      />
      <MetricCell
        value={`${load.toFixed(1)} MW`}
        label="Load"
        sub={loss > 0 ? `${loss.toFixed(1)} MW loss` : undefined}
      />
      <MetricCell
        value={`${surplus >= 0 ? "+" : ""}${surplus.toFixed(1)} MW`}
        label="Surplus / Deficit"
        colorClass={surplusColor(surplus)}
      />
      <MetricCell
        value={String(alertCount)}
        label="Active Alerts"
        colorClass={alertCount > 0 ? "text-accent-yellow" : "text-text-secondary"}
      />
      <MetricCell value={formatSimTime(simTime)} label="Sim Time" />
    </div>
  );
}
