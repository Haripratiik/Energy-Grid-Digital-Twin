import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "../../hooks/useGridStream";
import type { EstimateResponse } from "../../types/grid";
import { StatCard, LoadingNote } from "./shared";

export default function StateEstimationTab() {
  const [data, setData] = useState<EstimateResponse | null>(null);
  const [badData, setBadData] = useState(false);
  const [caseId, setCaseId] = useState("ieee118");
  const [loading, setLoading] = useState(false);

  const run = useCallback((c: string, bad: boolean) => {
    setLoading(true);
    fetch(`${API_BASE}/estimate?case=${c}&bad=${bad}`)
      .then((r) => r.json())
      .then((d: EstimateResponse) => setData(d))
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => run(caseId, badData), [caseId, badData, run]);

  const r = data?.result;
  const cases = [
    { id: "ieee14", label: "IEEE-14" },
    { id: "ieee30", label: "IEEE-30" },
    { id: "ieee118", label: "IEEE-118" },
  ];

  return (
    <div className="flex flex-col gap-4">
      <p className="font-mono text-[10px] text-text-secondary leading-relaxed">
        Weighted-least-squares state estimation: recover the true state from a redundant,
        noisy measurement set, then test for gross errors (χ² detection + largest normalized
        residual identification) — the EMS-standard estimator.
      </p>

      <div className="flex items-center gap-3 flex-wrap">
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
        <button
          onClick={() => setBadData((b) => !b)}
          className={`font-mono text-[10px] px-3 py-1 uppercase tracking-wider border transition-colors ${
            badData
              ? "border-accent-red bg-accent-red text-white"
              : "border-border-strong text-text-secondary hover:bg-bg-elevated"
          }`}
        >
          {badData ? "Gross error injected" : "Inject gross error"}
        </button>
        {loading && <LoadingNote text="estimating…" />}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <StatCard label="Redundancy" value={r ? `${r.redundancy.toFixed(1)}×` : "—"} sub={r ? `${r.n_measurements} meas / ${r.n_states} states` : ""} />
        <StatCard
          label="Flow RMSE"
          value={r ? r.flow_rmse_pu.toFixed(4) : "—"}
          unit="pu"
          sub={r ? `sensor noise ${r.measurement_noise_pu.toFixed(3)} — denoised` : ""}
          color="text-accent-green"
        />
        <StatCard
          label="χ² test  J / thr"
          value={r ? `${r.objective_j.toFixed(0)} / ${r.chi2_threshold.toFixed(0)}` : "—"}
          sub={r ? (r.bad_data_detected ? "bad data detected" : "within tolerance") : ""}
          color={r?.bad_data_detected ? "text-accent-red" : "text-accent-green"}
        />
        <StatCard
          label="Bad-data localization"
          value={r ? (r.flagged_measurement != null ? `meas #${r.flagged_measurement}` : "none") : "—"}
          sub={r ? `max norm. residual ${r.max_normalized_residual.toFixed(1)}` : ""}
          color={r?.flagged_measurement != null ? "text-accent-red" : "text-text-muted"}
        />
      </div>

      {r && (
        <div className="border border-border-subtle bg-bg-tertiary px-3 py-2">
          <p className="font-mono text-[10px] text-text-secondary leading-relaxed">
            {r.bad_data_detected ? (
              <>
                χ² statistic <span className="text-accent-red">J = {r.objective_j.toFixed(0)}</span>{" "}
                exceeds the threshold {r.chi2_threshold.toFixed(0)} ⇒ <span className="text-accent-red">bad data detected</span>.
                {data?.injected_bad_index != null && r.flagged_measurement === data.injected_bad_index && (
                  <> The largest normalized residual correctly points to measurement{" "}
                    <span className="text-accent-yellow">#{r.flagged_measurement}</span> — the injected error.</>
                )}
              </>
            ) : (
              <>
                χ² statistic <span className="text-accent-green">J = {r.objective_j.toFixed(0)}</span>{" "}
                is below the threshold {r.chi2_threshold.toFixed(0)} ⇒ measurements are consistent.
                The estimate's flow RMSE ({r.flow_rmse_pu.toFixed(4)} pu) is below the raw sensor
                noise ({r.measurement_noise_pu.toFixed(3)} pu) — redundancy denoises the state.
              </>
            )}
          </p>
        </div>
      )}
    </div>
  );
}
