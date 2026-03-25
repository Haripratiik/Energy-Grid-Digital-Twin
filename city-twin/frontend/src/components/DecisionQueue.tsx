import { useEffect, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { AutonomousMode, GridDecision, RiskLevel } from "../types/grid";

interface Props {
  pending: GridDecision[];
  mode: AutonomousMode;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onAssetClick?: (rid: string) => void;
}

const RISK_BADGE: Record<RiskLevel, string> = {
  ADVISORY: "bg-accent-blue/20 text-accent-blue border-accent-blue/40",
  CONTROLLED: "bg-accent-yellow/20 text-accent-yellow border-accent-yellow/40",
  CRITICAL: "bg-accent-red/20 text-accent-red border-accent-red/40",
  EMERGENCY: "bg-accent-red text-white border-accent-red pulse-red",
};

const RISK_CARD_BORDER: Record<RiskLevel, string> = {
  ADVISORY: "border-accent-blue/20",
  CONTROLLED: "border-accent-yellow/30",
  CRITICAL: "border-accent-red/40",
  EMERGENCY: "border-accent-red pulse-red",
};

const STATUS_BADGE: Record<string, string> = {
  PENDING: "bg-accent-yellow/15 text-accent-yellow",
  APPROVED: "bg-accent-green/15 text-accent-green",
  EXECUTED: "bg-accent-blue/15 text-accent-blue",
  REJECTED: "bg-border-strong text-text-muted",
  EXPIRED: "bg-border-strong text-text-muted",
  REVERTED: "bg-accent-red/15 text-accent-red",
};

function ridToLabel(rid: string): string {
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

function confidenceColor(pct: number): string {
  if (pct >= 80) return "text-accent-green";
  if (pct >= 65) return "text-accent-yellow";
  return "text-accent-red";
}

function outcomeLabel(delta: Record<string, number> | null): {
  text: string;
  cls: string;
} | null {
  if (!delta) return null;
  const total = Object.values(delta).reduce((s, v) => s + v, 0);
  return total >= 0
    ? { text: "IMPROVED", cls: "bg-accent-green/20 text-accent-green" }
    : { text: "BACKFIRED", cls: "bg-accent-red/20 text-accent-red" };
}

function CountdownBar({ expiresAt }: { expiresAt: string }) {
  const [remaining, setRemaining] = useState(() => {
    const ms = new Date(expiresAt).getTime() - Date.now();
    return Math.max(0, Math.floor(ms / 1000));
  });
  const [total] = useState(() => {
    const ms = new Date(expiresAt).getTime() - Date.now();
    return Math.max(1, Math.floor(ms / 1000));
  });

  useEffect(() => {
    const iv = setInterval(() => {
      const ms = new Date(expiresAt).getTime() - Date.now();
      setRemaining(Math.max(0, Math.floor(ms / 1000)));
    }, 1000);
    return () => clearInterval(iv);
  }, [expiresAt]);

  const pct = Math.min(100, ((total - remaining) / total) * 100);

  return (
    <div className="mt-1.5">
      <div className="flex items-center justify-between mb-0.5">
        <span className="font-mono text-[9px] text-text-muted uppercase">
          Auto-execute
        </span>
        <span className="font-mono text-[10px] text-accent-yellow">
          {remaining}s
        </span>
      </div>
      <div className="h-1 w-full bg-bg-elevated overflow-hidden">
        <motion.div
          className="h-full bg-accent-red"
          initial={false}
          animate={{ width: `${pct}%` }}
          transition={{ duration: 0.5, ease: "linear" }}
        />
      </div>
    </div>
  );
}

export default function DecisionQueue({
  pending,
  mode,
  onApprove,
  onReject,
  onAssetClick,
}: Props) {
  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-1.5 border-b border-border-strong bg-bg-tertiary flex items-center justify-between">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          <span className="text-accent-blue">04</span> Decision Queue
        </span>
        <div className="flex items-center gap-2">
          <span className={`font-mono text-[9px] px-1.5 py-0.5 uppercase tracking-wide ${
            mode === "FULL_AUTO"
              ? "bg-accent-green/15 text-accent-green border border-accent-green/30"
              : "bg-accent-yellow/15 text-accent-yellow border border-accent-yellow/30"
          }`}>
            {mode === "FULL_AUTO" ? "Full Auto" : "Semi Auto"}
          </span>
          <span className="font-mono text-[10px] text-text-secondary">
            {pending.length} pending
          </span>
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        <AnimatePresence initial={false}>
          {pending.map((d) => {
            const conf = d.action.confidence;
            const rationale = d.action.rationale;
            const outcome = outcomeLabel(d.outcome_delta);
            // In FULL_AUTO: only EMERGENCY needs manual approval
            // In SEMI: CRITICAL and EMERGENCY need manual approval
            const needsApproval =
              mode === "FULL_AUTO"
                ? d.risk_level === "EMERGENCY"
                : d.risk_level === "CRITICAL" || d.risk_level === "EMERGENCY";
            // Show countdown for auto-executing decisions
            const showCountdown =
              d.status === "PENDING" &&
              d.expires_at != null &&
              (d.risk_level === "CONTROLLED" ||
                (mode === "FULL_AUTO" && d.risk_level === "CRITICAL"));
            const isControlled = d.risk_level === "CONTROLLED";

            return (
              <motion.div
                key={d.id}
                layout
                initial={{ opacity: 0, x: 60 }}
                animate={{ opacity: 1, x: 0 }}
                exit={{ opacity: 0, x: -60, height: 0 }}
                transition={{ duration: 0.3, ease: "easeOut" }}
                className={`border bg-bg-secondary p-2.5 ${RISK_CARD_BORDER[d.risk_level]}`}
              >
                {/* row 1: risk badge + action + status */}
                <div className="flex items-center gap-2 flex-wrap">
                  <span
                    className={`font-mono text-[9px] px-1.5 py-0.5 border uppercase tracking-wide ${RISK_BADGE[d.risk_level]}`}
                  >
                    {d.risk_level}
                  </span>
                  <span className="font-mono text-xs text-text-primary">
                    {d.action.action_type}
                  </span>
                  <span className="font-mono text-[10px] text-text-muted">on</span>
                  <button
                    onClick={() => onAssetClick?.(d.action.target_rid)}
                    className="font-mono text-[10px] px-1.5 py-0.5 bg-bg-elevated border border-border-subtle text-text-code hover:bg-bg-tertiary transition-colors"
                  >
                    {ridToLabel(d.action.target_rid)}
                  </button>
                  <span className="ml-auto" />
                  <span
                    className={`font-mono text-[9px] px-1.5 py-0.5 ${STATUS_BADGE[d.status] ?? ""}`}
                  >
                    {d.status}
                  </span>
                </div>

                {/* row 2: rationale */}
                <p className="mt-1.5 text-[13px] font-sans text-text-secondary leading-snug">
                  {rationale}
                </p>

                {/* row 3: metrics row */}
                <div className="mt-1.5 flex items-center gap-3 flex-wrap">
                  {conf != null && (
                    <span
                      className={`font-mono text-[11px] ${confidenceColor(conf * 100)}`}
                    >
                      {(conf * 100).toFixed(0)}% confidence
                    </span>
                  )}
                  {d.action.estimated_impact_mw != null && (
                    <span className={`font-mono text-[11px] font-semibold ${
                      d.action.estimated_impact_mw > 0 ? "text-accent-green" : "text-accent-red"
                    }`}>
                      {d.action.estimated_impact_mw > 0 ? "+" : ""}
                      {d.action.estimated_impact_mw} MW
                    </span>
                  )}
                  {outcome && (
                    <span
                      className={`font-mono text-[9px] px-1.5 py-0.5 ${outcome.cls}`}
                    >
                      {outcome.text}
                    </span>
                  )}
                </div>

                {/* countdown bar for auto-executing decisions */}
                {showCountdown && (
                  <CountdownBar expiresAt={d.expires_at!} />
                )}

                {/* auto-execution label (no manual intervention needed) */}
                {!needsApproval && d.status === "PENDING" && !showCountdown && (
                  <div className="mt-2">
                    <span className="font-mono text-[9px] px-2 py-0.5 bg-accent-green/10 text-accent-green border border-accent-green/20 uppercase tracking-wide">
                      AI Auto-Executing
                    </span>
                  </div>
                )}

                {/* action buttons — only when manual approval is required */}
                {needsApproval && d.status === "PENDING" && (
                  <div className="mt-2 flex items-center gap-2">
                    <button
                      onClick={() => onApprove(d.id)}
                      className="font-mono text-[10px] px-4 py-1 bg-accent-green text-bg-primary uppercase tracking-wider hover:bg-accent-green/80 transition-colors"
                    >
                      Approve
                    </button>
                    <button
                      onClick={() => onReject(d.id)}
                      className="font-mono text-[10px] px-4 py-1 bg-border-strong text-text-secondary uppercase tracking-wider hover:bg-border-subtle transition-colors"
                    >
                      Reject
                    </button>
                  </div>
                )}
              </motion.div>
            );
          })}
        </AnimatePresence>

        {pending.length === 0 && (
          <div className="text-center text-text-muted font-mono text-xs py-12">
            No pending decisions
          </div>
        )}
      </div>
    </div>
  );
}
