import { useEffect, useMemo, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { GridAlert } from "../types/grid";

interface Props {
  alerts: GridAlert[];
  onAssetClick?: (rid: string) => void;
}

const SEVERITY_ICON: Record<string, string> = {
  INFO: "●",
  WARNING: "▲",
  CRITICAL: "◆",
};

const SEVERITY_COLOR: Record<string, string> = {
  INFO: "text-accent-blue",
  WARNING: "text-accent-yellow",
  CRITICAL: "text-accent-red",
};

const SEVERITY_CARD: Record<string, string> = {
  INFO: "border-l-accent-blue/40 bg-accent-blue/[0.03]",
  WARNING: "border-l-accent-yellow/50 bg-accent-yellow/[0.04]",
  CRITICAL: "border-l-accent-red/50 bg-accent-red/[0.06]",
};

const TYPE_LABELS: Record<string, string> = {
  LINE_OVERLOAD: "LINE OVERLOAD",
  LINE_TRIPPED: "LINE TRIPPED",
  CASCADE_IMMINENT: "CASCADE RISK",
  TRAFO_OVERLOAD: "TRAFO OVERLOAD",
  GEN_OFFLINE: "GEN OFFLINE",
  ANGLE_INSTABILITY: "ANGLE INSTAB.",
  FREQ_CRITICAL: "FREQ CRITICAL",
  FREQ_DEVIATION: "FREQ DEVIATION",
  VOLTAGE_LOW: "VOLTAGE LOW",
  VOLTAGE_CRITICAL: "VOLTAGE CRIT",
  CASCADE_RISK: "CASCADE RISK",
  FREQUENCY_DROP: "FREQ DROP",
  FREQUENCY_HIGH: "FREQ HIGH",
};

function ridToShortName(rid: string): string {
  const parts = rid.split(".");
  const type = parts[parts.length - 2] ?? "";
  const id = parts[parts.length - 1] ?? "";
  if (type === "transmission-line") return `Line ${id}`;
  if (type === "generator") return `Gen ${id}`;
  if (type === "load-bus") return `Bus ${id}`;
  if (type === "substation") return `Sub ${id}`;
  if (type === "transformer") return `Trafo ${id}`;
  return id;
}

function formatTime(simSec: number): string {
  const m = Math.floor(simSec / 60);
  const s = Math.floor(simSec % 60);
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

export default function AlertFeed({ alerts, onAssetClick }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = 0;
    }
  }, [alerts.length]);

  const sorted = useMemo(() => [...alerts].reverse().slice(0, 60), [alerts]);

  const counts = useMemo(() => {
    let crit = 0;
    let warn = 0;
    let info = 0;
    for (const a of alerts) {
      if (a.severity === "CRITICAL") crit++;
      else if (a.severity === "WARNING") warn++;
      else info++;
    }
    return { crit, warn, info };
  }, [alerts]);

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-1.5 border-b border-border-subtle bg-bg-tertiary flex items-center justify-between">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          Alerts
        </span>
        <div className="flex items-center gap-2 font-mono text-[9px]">
          {counts.crit > 0 && (
            <span className="text-accent-red">
              {counts.crit} CRIT
            </span>
          )}
          {counts.warn > 0 && (
            <span className="text-accent-yellow">
              {counts.warn} WARN
            </span>
          )}
          {counts.info > 0 && (
            <span className="text-accent-blue">
              {counts.info} INFO
            </span>
          )}
          {alerts.length === 0 && (
            <span className="text-text-muted">0</span>
          )}
        </div>
      </div>

      <div ref={scrollRef} className="flex-1 overflow-y-auto p-1.5 space-y-1">
        <AnimatePresence initial={false}>
          {sorted.map((alert) => (
            <motion.div
              key={alert.id}
              initial={{ opacity: 0, x: 30 }}
              animate={{ opacity: 1, x: 0 }}
              exit={{ opacity: 0, x: -30 }}
              transition={{ duration: 0.2 }}
              className={`border-l-2 border border-border-subtle/50 px-2.5 py-1.5 ${SEVERITY_CARD[alert.severity] ?? ""}`}
            >
              {/* Row 1: icon + type tag + time */}
              <div className="flex items-center gap-1.5">
                <span className={`text-[10px] ${SEVERITY_COLOR[alert.severity]}`}>
                  {SEVERITY_ICON[alert.severity]}
                </span>
                <span className={`font-mono text-[9px] uppercase tracking-wide ${SEVERITY_COLOR[alert.severity]}`}>
                  {TYPE_LABELS[alert.type] ?? alert.type}
                </span>
                <span className="ml-auto font-mono text-[9px] text-text-muted tabular-nums">
                  {formatTime(alert.timestamp_sim)}
                </span>
              </div>

              {/* Row 2: summary (main text) */}
              <p className="mt-0.5 text-[11px] text-text-secondary leading-snug">
                {alert.summary || fallbackSummary(alert)}
              </p>

              {/* Row 3: affected assets */}
              {alert.affected_asset_rids.length > 0 && (
                <div className="mt-1 flex flex-wrap gap-1">
                  {alert.affected_asset_rids.slice(0, 4).map((rid) => (
                    <button
                      key={rid}
                      onClick={() => onAssetClick?.(rid)}
                      className="font-mono text-[8px] px-1 py-0.5 bg-bg-elevated border border-border-subtle text-text-code hover:bg-bg-tertiary transition-colors"
                    >
                      {ridToShortName(rid)}
                    </button>
                  ))}
                  {alert.affected_asset_rids.length > 4 && (
                    <span className="font-mono text-[8px] text-text-muted px-1">
                      +{alert.affected_asset_rids.length - 4}
                    </span>
                  )}
                </div>
              )}
            </motion.div>
          ))}
        </AnimatePresence>

        {sorted.length === 0 && (
          <div className="text-center text-text-muted font-mono text-[10px] py-6">
            No active alerts — system nominal
          </div>
        )}
      </div>
    </div>
  );
}

function fallbackSummary(alert: GridAlert): string {
  const sv = alert.sensor_values;
  const keys = Object.keys(sv);
  if (keys.length === 0) return alert.type.replace(/_/g, " ").toLowerCase();
  return keys
    .map((k) => `${k}: ${typeof sv[k] === "number" ? sv[k].toFixed(2) : sv[k]}`)
    .join(", ");
}
