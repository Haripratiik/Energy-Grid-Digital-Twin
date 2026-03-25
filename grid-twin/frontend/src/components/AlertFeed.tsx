import { useEffect, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { GridAlert } from "../types/grid";

interface Props {
  alerts: GridAlert[];
  onAssetClick?: (rid: string) => void;
}

const severityStyle: Record<string, string> = {
  INFO: "bg-accent-blue/20 text-accent-blue border-accent-blue/30",
  WARNING: "bg-accent-yellow/10 text-accent-yellow border-accent-yellow/30",
  CRITICAL:
    "bg-accent-red-dim/30 text-accent-red border-accent-red pulse-red",
};

const badgeStyle: Record<string, string> = {
  INFO: "bg-accent-blue text-white",
  WARNING: "bg-accent-yellow/20 text-accent-yellow",
  CRITICAL: "bg-accent-red text-white",
};

function ridToShortName(rid: string): string {
  const parts = rid.split(".");
  const type = parts[parts.length - 2] ?? "";
  const id = parts[parts.length - 1] ?? "";
  if (type === "transmission-line") return `Line ${id}`;
  if (type === "generator") return `Gen ${id}`;
  if (type === "load-bus") return `Bus ${id}`;
  if (type === "substation") return `Sub ${id}`;
  return id;
}

function formatTime(sim_s: number): string {
  const m = Math.floor(sim_s / 60);
  const s = Math.floor(sim_s % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function AlertFeed({ alerts, onAssetClick }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [alerts.length]);

  const sorted = [...alerts].reverse().slice(0, 50);

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-border-subtle bg-bg-tertiary">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          Alert Feed
        </span>
      </div>
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-2 space-y-1.5">
        <AnimatePresence initial={false}>
          {sorted.map((alert) => (
            <motion.div
              key={alert.id}
              initial={{ opacity: 0, x: 40 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -40 }}
              transition={{ duration: 0.25 }}
              className={`border rounded px-2.5 py-1.5 ${severityStyle[alert.severity] ?? ""}`}
            >
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <span
                    className={`font-mono text-[9px] px-1.5 py-0.5 rounded ${badgeStyle[alert.severity] ?? ""}`}
                  >
                    {alert.severity}
                  </span>
                  <span className="font-mono text-xs text-text-primary">
                    {alert.type}
                  </span>
                </div>
                <span className="font-mono text-[10px] text-text-muted">
                  {formatTime(alert.timestamp_sim)}
                </span>
              </div>
              <div className="mt-1 flex flex-wrap gap-1">
                {alert.affected_asset_rids.map((rid) => (
                  <button
                    key={rid}
                    onClick={() => onAssetClick?.(rid)}
                    className="font-mono text-[9px] px-1.5 py-0.5 bg-bg-elevated border border-border-subtle text-text-code hover:bg-bg-tertiary transition-colors rounded"
                  >
                    {ridToShortName(rid)}
                  </button>
                ))}
              </div>
              {Object.keys(alert.sensor_values).length > 0 && (
                <div className="mt-1 font-mono text-[9px] text-text-secondary">
                  {Object.entries(alert.sensor_values)
                    .map(([k, v]) => `${k}=${typeof v === "number" ? v.toFixed(2) : v}`)
                    .join(", ")}
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>
        {sorted.length === 0 && (
          <div className="text-center text-text-muted font-mono text-xs py-8">
            No active alerts
          </div>
        )}
      </div>
    </div>
  );
}
