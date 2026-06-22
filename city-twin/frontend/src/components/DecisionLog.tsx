import { Fragment, useMemo, useState } from "react";
import type { GridDecision, RiskLevel } from "../types/grid";
import { VerdictBadge, CorrectionTrace } from "./VerificationView";

interface Props {
  decisions: GridDecision[];
  onRevert: (id: string) => void;
}

type StatusFilter = "ALL" | GridDecision["status"];

const FILTERS: StatusFilter[] = [
  "ALL",
  "PENDING",
  "EXECUTED",
  "REJECTED",
  "REVERTED",
];

const RISK_COLOR: Record<RiskLevel, string> = {
  ADVISORY: "text-accent-blue",
  CONTROLLED: "text-accent-yellow",
  CRITICAL: "text-accent-red",
  EMERGENCY: "text-accent-red font-bold",
};

const STATUS_STYLE: Record<string, string> = {
  PENDING: "text-accent-yellow",
  APPROVED: "text-accent-green",
  EXECUTED: "text-accent-blue",
  REJECTED: "text-text-muted",
  EXPIRED: "text-text-muted",
  REVERTED: "text-accent-red",
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

function formatTimestamp(iso: string | undefined | null): string {
  if (!iso) return "--:--:--";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "--:--:--";
  return d.toLocaleTimeString("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function outcomeText(
  delta: Record<string, number> | null
): { text: string; cls: string } | null {
  if (!delta) return null;
  const total = Object.values(delta).reduce((s, v) => s + v, 0);
  return total >= 0
    ? { text: "IMPROVED", cls: "text-accent-green" }
    : { text: "BACKFIRED", cls: "text-accent-red" };
}

export default function DecisionLog({ decisions, onRevert }: Props) {
  const [filter, setFilter] = useState<StatusFilter>("ALL");
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const toggle = (id: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });

  const filtered = useMemo(() => {
    const base =
      filter === "ALL" ? decisions : decisions.filter((d) => d.status === filter);
    // Newest first, and keep the 100 MOST RECENT (not the 100 oldest, which is
    // what a plain slice of an insertion-ordered list would show).
    return [...base]
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
      .slice(0, 100);
  }, [decisions, filter]);

  return (
    <div className="flex flex-col h-full">
      {/* header */}
      <div className="px-3 py-1.5 border-b border-border-strong bg-bg-tertiary flex items-center gap-3">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          Audit Log
        </span>
        <div className="flex items-center gap-1 ml-auto">
          {FILTERS.map((f) => (
            <button
              key={f}
              onClick={() => setFilter(f)}
              className={`font-mono text-[9px] px-2 py-0.5 uppercase tracking-wide transition-colors ${
                filter === f
                  ? "bg-accent-blue/20 text-accent-blue border border-accent-blue/30"
                  : "text-text-muted hover:text-text-secondary border border-transparent"
              }`}
            >
              {f}
            </button>
          ))}
        </div>
      </div>

      {/* table */}
      <div className="flex-1 overflow-y-auto">
        <table className="w-full text-left">
          <thead className="sticky top-0 bg-bg-tertiary z-10">
            <tr className="border-b border-border-subtle">
              {["Time", "Risk", "Action", "Target", "Status", "Physics", "By", "Outcome", ""].map(
                (h) => (
                  <th
                    key={h}
                    className="font-mono text-[9px] text-text-muted uppercase tracking-wider px-2 py-1.5 font-normal"
                  >
                    {h}
                  </th>
                )
              )}
            </tr>
          </thead>
          <tbody>
            {filtered.map((d) => {
              const outcome = outcomeText(d.outcome_delta);
              const canRevert =
                d.status === "EXECUTED" && d.action.reversible !== false;
              const hasDetail =
                d.verification != null || (d.correction_trace?.length ?? 0) > 1;
              const isOpen = expanded.has(d.id);

              return (
                <Fragment key={d.id}>
                <tr
                  onClick={() => hasDetail && toggle(d.id)}
                  className={`border-b border-border-subtle/50 hover:bg-bg-elevated/40 transition-colors ${
                    hasDetail ? "cursor-pointer" : ""
                  }`}
                >
                  <td className="font-mono text-[10px] text-text-secondary px-2 py-1 whitespace-nowrap">
                    {formatTimestamp(d.timestamp)}
                  </td>
                  <td
                    className={`font-mono text-[10px] px-2 py-1 ${RISK_COLOR[d.risk_level]}`}
                  >
                    {d.risk_level}
                  </td>
                  <td className="font-mono text-[10px] text-text-primary px-2 py-1">
                    {d.action.action_type}
                  </td>
                  <td className="font-mono text-[10px] text-text-code px-2 py-1">
                    {ridToLabel(d.action.target_rid)}
                  </td>
                  <td
                    className={`font-mono text-[10px] px-2 py-1 ${STATUS_STYLE[d.status] ?? "text-text-muted"}`}
                  >
                    {d.status}
                  </td>
                  <td className="px-2 py-1 whitespace-nowrap">
                    {d.verification ? (
                      <span
                        title={d.verification.reason}
                        className={`font-mono text-[9px] ${
                          d.verification.safe ? "text-accent-green" : "text-accent-red"
                        }`}
                      >
                        <span className="text-text-muted">{isOpen ? "▾ " : "▸ "}</span>
                        {d.verification.safe ? "✓ verified" : "✕ blocked"}
                        {d.correction_trace && d.correction_trace.length > 1 ? " ⟳" : ""}
                      </span>
                    ) : (
                      <span className="font-mono text-[9px] text-text-muted">—</span>
                    )}
                  </td>
                  <td className="font-mono text-[10px] text-text-muted px-2 py-1">
                    {d.executed_by ?? "—"}
                  </td>
                  <td className="px-2 py-1">
                    {outcome ? (
                      <span className={`font-mono text-[9px] ${outcome.cls}`}>
                        {outcome.text}
                      </span>
                    ) : (
                      <span className="font-mono text-[9px] text-text-muted">
                        —
                      </span>
                    )}
                  </td>
                  <td className="px-2 py-1">
                    {canRevert && (
                      <button
                        onClick={(e) => {
                          e.stopPropagation();
                          onRevert(d.id);
                        }}
                        className="font-mono text-[9px] px-2 py-0.5 border border-accent-red/40 text-accent-red hover:bg-accent-red/10 transition-colors uppercase tracking-wide"
                      >
                        Revert
                      </button>
                    )}
                  </td>
                </tr>
                {hasDetail && isOpen && (
                  <tr className="bg-bg-primary/40">
                    <td colSpan={9} className="px-3 pb-2 pt-0">
                      <CorrectionTrace trace={d.correction_trace} />
                      {d.verification && <VerdictBadge v={d.verification} />}
                    </td>
                  </tr>
                )}
                </Fragment>
              );
            })}
            {filtered.length === 0 && (
              <tr>
                <td
                  colSpan={9}
                  className="text-center font-mono text-xs text-text-muted py-8"
                >
                  No decisions match filter
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
