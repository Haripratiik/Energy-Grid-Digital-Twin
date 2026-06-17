import { useEffect, useMemo, useRef, useState } from "react";
import { API_BASE } from "../hooks/useGridStream";
import type {
  ContingencyOutcome,
  ContingencyReport,
  ContingencyResult,
  ContingencySummary,
} from "../types/grid";

interface Props {
  /** Live compact summary from the SSE stream (instant status). */
  summary?: ContingencySummary | null;
}

const OUTCOME_STYLE: Record<ContingencyOutcome, { dot: string; text: string; label: string }> = {
  SECURE: { dot: "bg-accent-green", text: "text-accent-green", label: "SECURE" },
  THERMAL_OVERLOAD: { dot: "bg-accent-yellow", text: "text-accent-yellow", label: "OVERLOAD" },
  VOLTAGE_VIOLATION: { dot: "bg-orange-500", text: "text-orange-400", label: "VOLTAGE" },
  COLLAPSE: { dot: "bg-accent-red", text: "text-accent-red", label: "COLLAPSE" },
};

const KIND_TAG: Record<ContingencyResult["kind"], string> = {
  LINE: "L",
  TRANSFORMER: "T",
  GENERATOR: "G",
};

function severityColor(outcome: ContingencyOutcome): string {
  switch (outcome) {
    case "COLLAPSE":
      return "#e53e3e";
    case "VOLTAGE_VIOLATION":
      return "#f97316";
    case "THERMAL_OVERLOAD":
      return "#f0a500";
    default:
      return "#363b47";
  }
}

export default function ContingencyPanel({ summary }: Props) {
  const [report, setReport] = useState<ContingencyReport | null>(null);
  const [loading, setLoading] = useState(true);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    const fetchReport = async () => {
      try {
        const res = await fetch(`${API_BASE}/contingencies?limit=40`);
        const data: ContingencyReport = await res.json();
        if (mounted.current) {
          setReport(data);
          setLoading(false);
        }
      } catch {
        if (mounted.current) setLoading(false);
      }
    };
    fetchReport();
    const id = setInterval(fetchReport, 4000);
    return () => {
      mounted.current = false;
      clearInterval(id);
    };
  }, []);

  // Live status comes from the SSE summary if present, else the polled report.
  const baseSecure = summary?.base_secure ?? report?.base_secure ?? true;
  const nInsecure = summary?.n_insecure ?? report?.n_insecure ?? 0;
  const nScreened = summary?.n_screened ?? report?.n_screened ?? 0;

  const maxSeverity = useMemo(() => {
    if (!report?.results.length) return 1;
    return Math.max(1, ...report.results.map((r) => r.severity));
  }, [report]);

  const insecure = report?.results.filter((r) => r.outcome !== "SECURE") ?? [];

  return (
    <div className="flex flex-col h-full bg-bg-primary">
      {/* header */}
      <div className="px-3 py-1.5 border-b border-border-strong bg-bg-tertiary flex items-center justify-between">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          N-1 Contingency Analysis
        </span>
        <span
          className={`font-mono text-[10px] uppercase tracking-wider px-1.5 py-0.5 ${
            baseSecure
              ? "text-accent-green border border-accent-green/30"
              : "text-accent-red border border-accent-red/40"
          }`}
        >
          {baseSecure ? "N-1 Secure" : `${nInsecure} Insecure`}
        </span>
      </div>

      {/* status strip */}
      <div className="px-3 py-2 border-b border-border-subtle flex items-center gap-4">
        <div className="flex flex-col">
          <span className="font-mono text-[9px] text-text-muted uppercase tracking-wider">
            Screened
          </span>
          <span className="font-mono text-[15px] text-text-primary tabular-nums leading-tight">
            {nScreened}
          </span>
        </div>
        <div className="flex flex-col">
          <span className="font-mono text-[9px] text-text-muted uppercase tracking-wider">
            Insecure
          </span>
          <span
            className={`font-mono text-[15px] tabular-nums leading-tight ${
              nInsecure > 0 ? "text-accent-red" : "text-accent-green"
            }`}
          >
            {nInsecure}
          </span>
        </div>
        {report?.worst && (
          <div className="flex flex-col min-w-0 flex-1">
            <span className="font-mono text-[9px] text-text-muted uppercase tracking-wider">
              Worst Case
            </span>
            <span
              className="font-mono text-[11px] text-text-secondary leading-tight truncate"
              title={report.worst.label}
            >
              {report.worst.label}
            </span>
          </div>
        )}
      </div>

      {/* ranked list */}
      <div className="flex-1 overflow-y-auto">
        {loading && (
          <div className="px-3 py-4 font-mono text-[10px] text-text-muted">
            screening contingencies…
          </div>
        )}

        {!loading && insecure.length === 0 && (
          <div className="px-3 py-4 font-mono text-[10px] text-accent-green">
            ✓ Grid is N-1 secure — no single contingency violates a limit.
          </div>
        )}

        {insecure.map((r) => {
          const style = OUTCOME_STYLE[r.outcome];
          const widthPct = Math.min(100, (r.severity / maxSeverity) * 100);
          return (
            <div
              key={r.contingency_id}
              className="px-3 py-1.5 border-b border-border-subtle/50 hover:bg-bg-secondary transition-colors"
            >
              <div className="flex items-center gap-2">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${style.dot}`} />
                <span className="font-mono text-[9px] text-text-muted w-3 shrink-0">
                  {KIND_TAG[r.kind]}
                </span>
                <span
                  className="font-mono text-[10px] text-text-primary truncate flex-1"
                  title={r.label}
                >
                  {r.label}
                </span>
                <span className={`font-mono text-[9px] uppercase tracking-wider shrink-0 ${style.text}`}>
                  {style.label}
                </span>
                <span className="font-mono text-[10px] text-text-secondary tabular-nums w-12 text-right shrink-0">
                  {r.severity.toFixed(1)}
                </span>
              </div>
              {/* severity bar */}
              <div className="mt-1 ml-[18px] h-[3px] bg-bg-tertiary overflow-hidden">
                <div
                  className="h-full transition-[width] duration-300 ease-out"
                  style={{ width: `${widthPct}%`, background: severityColor(r.outcome) }}
                />
              </div>
              {/* worst metrics */}
              <div className="mt-0.5 ml-[18px] flex gap-3 font-mono text-[9px] text-text-muted">
                {r.worst_loading_pct != null && (
                  <span>
                    load <span className="text-text-secondary">{r.worst_loading_pct.toFixed(0)}%</span>
                  </span>
                )}
                {r.worst_voltage_pu != null && (
                  <span>
                    V <span className="text-text-secondary">{r.worst_voltage_pu.toFixed(3)}pu</span>
                  </span>
                )}
                <span>
                  {r.n_violations} viol
                </span>
              </div>
            </div>
          );
        })}
      </div>

      {/* footer note */}
      <div className="px-3 py-1 border-t border-border-subtle bg-bg-tertiary">
        <span className="font-mono text-[9px] text-text-muted tracking-wide">
          DC-screen → AC-verify · {report?.n_ac_verified ?? 0} AC-verified
        </span>
      </div>
    </div>
  );
}
