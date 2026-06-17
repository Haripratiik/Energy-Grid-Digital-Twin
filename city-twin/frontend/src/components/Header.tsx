import { useMemo } from "react";
import { API_BASE } from "../hooks/useGridStream";
import type { ConnectionStatus } from "../hooks/useGridStream";
import type { GridState, AutonomousMode } from "../types/grid";
import type { DemoStatus } from "../hooks/useDemoStatus";

interface Props {
  gridState: GridState | null;
  connectionStatus: ConnectionStatus;
  mode: AutonomousMode;
  demo: DemoStatus;
  onToggleMode: () => void;
  onOpenTwin: () => void;
  appMode: "operations" | "testing";
  onToggleAppMode: () => void;
  onResetLayout: () => void;
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

const STATUS_DOT: Record<ConnectionStatus, string> = {
  connected: "bg-accent-green",
  connecting: "bg-accent-yellow animate-pulse",
  disconnected: "bg-accent-red",
};

function KpiCell({ label, value, unit, color }: { label: string; value: string; unit?: string; color?: string }) {
  return (
    <div className="flex flex-col items-center px-3 sm:px-4">
      <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest leading-none mb-1">
        {label}
      </span>
      <span className={`font-mono text-2xl sm:text-[28px] font-bold tabular-nums leading-none tracking-tight ${color ?? "text-text-primary"}`}>
        {value}
        {unit && (
          <span className="text-base sm:text-lg text-text-muted ml-1 font-semibold">
            {unit}
          </span>
        )}
      </span>
    </div>
  );
}

export default function Header({
  gridState,
  connectionStatus,
  mode,
  demo,
  onToggleMode,
  onOpenTwin,
  appMode,
  onToggleAppMode,
  onResetLayout,
}: Props) {
  const testing = appMode === "testing";
  const freq = gridState?.system_frequency_hz ?? 60.0;
  const genMw = gridState?.total_generation_mw ?? 0;
  const loadMw = gridState?.total_load_mw ?? 0;
  const margin = genMw - loadMw;

  const critAlerts = useMemo(() => {
    if (!gridState?.active_alerts) return 0;
    return gridState.active_alerts.filter((a) => a.severity === "CRITICAL").length;
  }, [gridState?.active_alerts]);

  const handleDemo = async () => {
    if (demo.active) return;
    try {
      await fetch(`${API_BASE}/demo`, { method: "POST" });
    } catch { /* next poll */ }
  };

  const handleRestore = async () => {
    try {
      await fetch(`${API_BASE}/restore`, { method: "POST" });
    } catch { /* next poll */ }
  };

  return (
    <header className="shrink-0 border-b border-border-strong bg-bg-secondary">
      {/* Main row */}
      <div className="min-h-[52px] h-[52px] flex items-center justify-between px-4 gap-2">
        {/* Left: branding + sim clock */}
        <div className="flex items-center gap-3 min-w-0 shrink">
          <span
            className={`w-2.5 h-2.5 rounded-full shrink-0 ${STATUS_DOT[connectionStatus]}`}
            title={connectionStatus}
          />
          <span className="font-mono text-[11px] text-text-secondary tracking-widest uppercase whitespace-nowrap hidden sm:inline">
            Atlanta Metro Grid Digital Twin
          </span>
          <span className="font-mono text-[11px] text-text-muted hidden sm:inline">|</span>
          <span className="font-mono text-lg sm:text-xl font-semibold text-text-primary tabular-nums whitespace-nowrap">
            {gridState ? formatSimTime(gridState.sim_time_s) : "--:--:--"}
          </span>
        </div>

        {/* Center: frequency hero */}
        <div className="flex items-baseline gap-1.5 shrink-0">
          <span className="font-mono text-[11px] text-text-muted uppercase tracking-wider hidden md:inline">
            Freq
          </span>
          <span className={`font-mono text-3xl sm:text-4xl font-bold tabular-nums ${freqColor(freq)}`}>
            {freq.toFixed(3)}
          </span>
          <span className="font-mono text-sm sm:text-base text-text-muted">Hz</span>
        </div>

        {/* Right: controls */}
        <div className="flex items-center gap-2 shrink-0">
          {/* Operations (clean monitoring) ↔ Testing (fault-injection sandbox) */}
          <button
            onClick={onToggleAppMode}
            className="flex items-center h-7 rounded-full overflow-hidden border border-border-strong"
            title={
              testing
                ? "Testing: fault-injection sandbox enabled"
                : "Operations: clean real-time monitoring (no self-inflicted faults)"
            }
          >
            <span className={`font-mono text-[10px] px-2.5 h-full flex items-center uppercase tracking-wider transition-all duration-200 ${
              !testing ? "bg-accent-green text-bg-primary" : "bg-transparent text-text-muted"
            }`}>
              Ops
            </span>
            <span className={`font-mono text-[10px] px-2.5 h-full flex items-center uppercase tracking-wider transition-all duration-200 ${
              testing ? "bg-accent-yellow text-bg-primary" : "bg-transparent text-text-muted"
            }`}>
              Test
            </span>
          </button>

          <button
            onClick={onOpenTwin}
            className="font-mono text-[10px] px-2.5 py-1.5 uppercase tracking-wider border border-accent-green/60 text-accent-green hover:bg-accent-green hover:text-bg-primary transition-colors"
            title="Digital twin — real-time state estimation (UKF)"
          >
            Digital Twin
          </button>
          <button
            onClick={onResetLayout}
            className="font-mono text-[10px] px-2.5 py-1.5 uppercase tracking-wider border border-border-strong text-text-secondary hover:bg-bg-elevated transition-colors"
            title="Reset panel layout to default"
          >
            Reset Layout
          </button>

          {/* Sandbox controls — testing mode only */}
          {testing && (
            <>
              <button
                onClick={handleDemo}
                disabled={demo.active}
                className={`font-mono text-[10px] px-2.5 py-1.5 uppercase tracking-wider transition-colors border ${
                  demo.active
                    ? "border-accent-yellow/40 text-accent-yellow/60 cursor-not-allowed"
                    : "border-accent-blue text-accent-blue hover:bg-accent-blue hover:text-white"
                }`}
              >
                {demo.active ? "Demo" : "Run Demo"}
              </button>
              <button
                onClick={handleRestore}
                className="font-mono text-[10px] px-2.5 py-1.5 uppercase tracking-wider border border-border-strong text-text-secondary hover:bg-bg-elevated transition-colors"
              >
                Restore
              </button>
            </>
          )}

          <button
            onClick={onToggleMode}
            className="flex items-center h-7 rounded-full overflow-hidden border border-border-strong"
            title={
              mode === "SEMI"
                ? "Semi-Autonomous: CRITICAL decisions require approval"
                : "Fully Autonomous: all decisions auto-execute"
            }
          >
            <span
              className={`font-mono text-[10px] px-2.5 h-full flex items-center uppercase tracking-wider transition-all duration-200 ${
                mode === "SEMI"
                  ? "bg-accent-blue text-white"
                  : "bg-transparent text-text-muted"
              }`}
            >
              Semi
            </span>
            <span
              className={`font-mono text-[10px] px-2.5 h-full flex items-center uppercase tracking-wider transition-all duration-200 ${
                mode === "FULL_AUTO"
                  ? "bg-accent-red text-white pulse-red"
                  : "bg-transparent text-text-muted"
              }`}
            >
              Auto
            </span>
          </button>
        </div>
      </div>

      {/* KPI strip */}
      <div className="min-h-[52px] h-[52px] flex items-center justify-between px-2 sm:px-4 border-t border-border-subtle bg-[#0c0e12] gap-2">
        <div className="flex items-stretch gap-0 divide-x divide-border-subtle overflow-x-auto">
          <KpiCell label="Gen" value={genMw.toFixed(0)} unit="MW" />
          <KpiCell label="Load" value={loadMw.toFixed(0)} unit="MW" />
          <KpiCell
            label="Margin"
            value={`${margin >= 0 ? "+" : ""}${margin.toFixed(0)}`}
            unit="MW"
            color={margin >= 0 ? "text-accent-green" : "text-accent-red"}
          />
          <KpiCell label="Loss" value={(gridState?.total_loss_mw ?? 0).toFixed(1)} unit="MW" />
          <KpiCell
            label="Crit"
            value={String(critAlerts)}
            color={critAlerts > 0 ? "text-accent-red" : "text-text-muted"}
          />
        </div>

        {demo.active && demo.phase && (
          <div className="hidden md:flex items-center gap-2 shrink-0 max-w-[40%]">
            <span className="w-2 h-2 rounded-full bg-accent-yellow animate-pulse shrink-0" />
            <span className="font-mono text-[11px] text-accent-yellow tracking-wide truncate" title={demo.phase}>
              {demo.phase}
            </span>
          </div>
        )}

        {!demo.active && (
          <span className="font-mono text-[10px] text-text-muted tracking-widest uppercase hidden lg:inline shrink-0">
            Palantir AIP · ADE
          </span>
        )}
      </div>
    </header>
  );
}
