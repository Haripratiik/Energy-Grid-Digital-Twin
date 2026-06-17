import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "../../hooks/useGridStream";
import type { LodfBenchRow } from "../../types/grid";
import { Metric, LoadingNote } from "./shared";

export default function PerformanceTab() {
  const [row, setRow] = useState<LodfBenchRow | null>(null);
  const [caseId, setCaseId] = useState("ieee118");
  const [busy, setBusy] = useState(false);

  const run = useCallback((c: string) => {
    setBusy(true);
    setRow(null);
    fetch(`${API_BASE}/perf/lodf?case=${c}`)
      .then((r) => r.json())
      .then((d: LodfBenchRow) => setRow(d))
      .catch(() => undefined)
      .finally(() => setBusy(false));
  }, []);

  useEffect(() => run(caseId), [caseId, run]);

  const cases = [
    { id: "ieee118", label: "IEEE-118" },
    { id: "case300", label: "300-bus" },
    { id: "case1354", label: "1354-bus" },
    { id: "case2869", label: "2869-bus" },
  ];

  return (
    <div className="flex flex-col gap-4">
      <p className="font-mono text-[10px] text-text-secondary leading-relaxed">
        N-1 contingency screening via PTDF/LODF distribution factors: all single-branch outages
        evaluated in one vectorised matrix expression instead of N power-flow solves — exact for
        the DC model, scaling to thousands of buses.
      </p>

      <div className="flex items-center gap-2 flex-wrap">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-wider">Network</span>
        <div className="flex border border-border-strong">
          {cases.map((c) => (
            <button
              key={c.id}
              onClick={() => setCaseId(c.id)}
              className={`font-mono text-[10px] px-2.5 py-1 uppercase tracking-wider transition-colors ${
                caseId === c.id ? "bg-accent-blue text-white" : "text-text-muted hover:text-text-secondary"
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>
        {busy && <LoadingNote text={caseId === "case2869" ? "building 2869-bus model…" : "benchmarking…"} />}
      </div>

      <div className="border border-border-subtle bg-bg-tertiary">
        <div className="grid grid-cols-2 md:grid-cols-4 divide-x divide-y md:divide-y-0 divide-border-subtle">
          <Metric label="Branches (contingencies)" value={busy ? "…" : String(row?.n_branch ?? "—")} />
          <Metric label="LODF screen (all)" value={busy ? "…" : row ? row.lodf_screen_ms.toFixed(2) : "—"} unit="ms" color="text-accent-green" />
          <Metric label="Speedup vs brute force" value={busy ? "…" : row ? `${row.speedup.toFixed(0)}×` : "—"} color="text-accent-blue" />
          <Metric label="Screening rate" value={busy ? "…" : row ? Math.round(row.contingencies_per_s).toLocaleString() : "—"} unit="/s" />
        </div>
      </div>

      {row && (
        <p className="font-mono text-[10px] text-text-secondary leading-relaxed">
          Screened <span className="text-text-primary">{row.n_branch}</span> N-1 contingencies on a{" "}
          <span className="text-text-primary">{row.n_bus}-bus</span> grid in{" "}
          <span className="text-accent-green">{row.lodf_screen_ms.toFixed(2)} ms</span> —{" "}
          <span className="text-accent-blue">{row.speedup.toFixed(0)}×</span> faster than{" "}
          {row.bruteforce_projected ? "projected " : ""}brute-force re-solves
          ({(row.bruteforce_ms / 1000).toFixed(1)} s), exact to{" "}
          {row.max_error_pu.toExponential(0)} pu.
        </p>
      )}
    </div>
  );
}
