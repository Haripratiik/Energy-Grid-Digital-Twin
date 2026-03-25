import { useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { GridAlert, GridState } from "../types/grid";

interface Props {
  gridState: GridState | null;
}

const TYPE_SHORT: Record<string, string> = {
  FREQ_CRITICAL: "Frequency critical",
  FREQ_DEVIATION: "Frequency deviation",
  VOLTAGE_CRITICAL: "Voltage critical",
  VOLTAGE_LOW: "Voltage low",
  CASCADE_IMMINENT: "Cascade risk",
  ANGLE_INSTABILITY: "Angle instability",
  LINE_OVERLOAD: "Line overload",
  LINE_TRIPPED: "Line tripped",
  TRAFO_OVERLOAD: "Transformer overload",
  GEN_OFFLINE: "Generator offline",
};

function typeLabel(t: string): string {
  return TYPE_SHORT[t] ?? t.replace(/_/g, " ");
}

export default function CriticalIssuesPopup({ gridState }: Props) {
  const critical = useMemo(
    () =>
      gridState?.active_alerts?.filter((a) => a.severity === "CRITICAL") ?? [],
    [gridState?.active_alerts],
  );
  const warnings = useMemo(
    () =>
      gridState?.active_alerts?.filter((a) => a.severity === "WARNING") ?? [],
    [gridState?.active_alerts],
  );

  const fingerprint = useMemo(
    () => critical.map((a) => a.id).sort().join("|"),
    [critical],
  );

  const [dismissedFp, setDismissedFp] = useState<string | null>(null);
  const visible =
    critical.length > 0 && fingerprint !== dismissedFp;

  return (
    <AnimatePresence>
      {visible && (
        <motion.div
          key={fingerprint}
          role="alert"
          aria-live="assertive"
          initial={{ opacity: 0, y: -16, scale: 0.96 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          exit={{ opacity: 0, y: -12, scale: 0.98 }}
          transition={{ type: "spring", stiffness: 420, damping: 32 }}
          className="fixed left-1/2 z-[200] w-[min(92vw,560px)] -translate-x-1/2 pointer-events-auto top-[118px] sm:top-[120px]"
        >
          <div className="rounded-md border border-accent-red/50 bg-[#1a0f0f] shadow-[0_8px_40px_rgba(0,0,0,0.55)] overflow-hidden">
            <div className="flex items-start justify-between gap-3 px-4 py-2.5 border-b border-accent-red/25 bg-accent-red/15">
              <div className="flex items-center gap-2 min-w-0">
                <span className="shrink-0 w-2 h-2 rounded-full bg-accent-red animate-pulse" />
                <h2 className="font-mono text-sm font-bold text-accent-red uppercase tracking-wide">
                  Critical issues
                </h2>
                <span className="font-mono text-xs text-text-muted tabular-nums">
                  ({critical.length})
                </span>
              </div>
              <button
                type="button"
                onClick={() => setDismissedFp(fingerprint)}
                className="shrink-0 font-mono text-[10px] px-2 py-1 text-text-secondary hover:text-text-primary border border-border-strong hover:border-border-subtle rounded transition-colors"
              >
                Dismiss
              </button>
            </div>

            <ul className="px-4 py-3 space-y-2.5 max-h-[40vh] overflow-y-auto">
              {critical.map((a) => (
                <li
                  key={a.id}
                  className="border-l-2 border-accent-red pl-3 py-0.5"
                >
                  <div className="font-mono text-[11px] text-accent-red/90 uppercase tracking-wide">
                    {typeLabel(a.type)}
                  </div>
                  <p className="mt-0.5 text-[13px] text-text-primary leading-snug">
                    {a.summary ||
                      Object.entries(a.sensor_values)
                        .map(([k, v]) => `${k}: ${typeof v === "number" ? v.toFixed(2) : v}`)
                        .join(" · ")}
                  </p>
                </li>
              ))}
            </ul>

            {warnings.length > 0 && (
              <div className="px-4 pb-3 pt-0 border-t border-border-subtle/80">
                <div className="font-mono text-[10px] text-accent-yellow uppercase tracking-wider mt-2 mb-1.5">
                  Warnings ({warnings.length})
                </div>
                <ul className="space-y-1.5 max-h-[28vh] overflow-y-auto">
                  {warnings.slice(0, 6).map((a) => (
                    <li
                      key={a.id}
                      className="text-[12px] text-text-secondary leading-snug pl-2 border-l border-accent-yellow/30"
                    >
                      <span className="font-mono text-[10px] text-accent-yellow">
                        {typeLabel(a.type)}
                      </span>
                      {" — "}
                      {a.summary || a.type}
                    </li>
                  ))}
                  {warnings.length > 6 && (
                    <li className="text-[11px] text-text-muted pl-2">
                      +{warnings.length - 6} more…
                    </li>
                  )}
                </ul>
              </div>
            )}
          </div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
