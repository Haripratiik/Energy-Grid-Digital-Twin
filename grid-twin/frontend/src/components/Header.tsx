import { API_BASE } from "../hooks/useGridStream";
import type { ConnectionStatus } from "../hooks/useGridStream";
import type { GridState } from "../types/grid";

interface Props {
  gridState: GridState | null;
  connectionStatus: ConnectionStatus;
}

function formatSimTime(seconds: number): string {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function freqColor(hz: number): string {
  const dev = Math.abs(hz - 60.0);
  if (dev > 1.0) return "text-accent-red";
  if (dev > 0.5) return "text-accent-yellow";
  return "text-accent-green";
}

const statusDot: Record<ConnectionStatus, string> = {
  connected: "bg-accent-green",
  connecting: "bg-accent-yellow",
  disconnected: "bg-accent-red",
};

export default function Header({ gridState, connectionStatus }: Props) {
  const freq = gridState?.system_frequency_hz ?? 60.0;

  const handleDemo = async () => {
    try {
      await fetch(`${API_BASE}/demo`, { method: "POST" });
    } catch {}
  };

  return (
    <header className="h-10 flex items-center justify-between px-4 bg-bg-secondary border-b border-border-subtle shrink-0">
      <div className="font-mono text-xs text-text-secondary tracking-widest uppercase">
        Grid Twin · Palantir AIP · IEEE 9-Bus
      </div>

      <div className="flex items-center gap-6">
        <button
          onClick={handleDemo}
          className="font-mono text-[10px] px-3 py-1 border border-accent-blue text-accent-blue hover:bg-accent-blue hover:text-white transition-colors uppercase tracking-wider"
        >
          Run Demo Scenario
        </button>

        <span className="font-mono text-sm text-text-primary">
          {gridState ? formatSimTime(gridState.sim_time_s) : "--:--:--"}
        </span>

        <span className={`font-mono text-lg font-semibold ${freqColor(freq)}`}>
          {freq.toFixed(2)} Hz
        </span>

        <span
          className={`w-2 h-2 rounded-full ${statusDot[connectionStatus]}`}
          title={connectionStatus}
        />
      </div>
    </header>
  );
}
