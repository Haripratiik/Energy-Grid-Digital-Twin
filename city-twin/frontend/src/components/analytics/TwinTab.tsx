import { useCallback, useEffect, useState } from "react";
import { useReducedMotion } from "framer-motion";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ReferenceArea,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { API_BASE } from "../../hooks/useGridStream";
import type { TwinRunResponse } from "../../types/grid";
import { StatCard, ChartFrame, Legend, TimeTooltip, LoadingNote } from "./shared";

type Observability = "full" | "partial";
const MEASURED: Record<Observability, string> = { full: "0,1,2", partial: "0,2" };
const SENSOR_NOISE_RAD = 0.01;

export default function TwinTab() {
  const reduce = useReducedMotion();
  const [data, setData] = useState<TwinRunResponse | null>(null);
  const [obs, setObs] = useState<Observability>("full");
  const [loading, setLoading] = useState(false);

  const run = useCallback((observability: Observability) => {
    setLoading(true);
    fetch(`${API_BASE}/twin/run?steps=600&anomaly_step=400&measured=${MEASURED[observability]}`)
      .then((r) => r.json())
      .then((d: TwinRunResponse) => setData(d))
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => run(obs), [obs, run]);

  const summary = data?.summary;
  const anomalyT = data?.anomaly_step != null ? data.anomaly_step * data.dt_s : null;
  const lastT = data?.steps.length ? data.steps[data.steps.length - 1].t : 0;
  const chartData = data?.steps ?? [];

  return (
    <div className="flex flex-col gap-4">
      <p className="font-mono text-[10px] text-text-secondary leading-relaxed">
        An Unscented Kalman Filter tracks a noisy physical plant (IEEE-9, 3 machines) from
        partial rotor-angle measurements — reconstructing unmeasured states and flagging
        when reality diverges from the model.
      </p>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
        <StatCard label="Angle RMSE" value={summary ? summary.converged_angle_rmse.toExponential(1) : "—"} unit="rad" sub={`sensor noise ${SENSOR_NOISE_RAD} — filter denoises`} color="text-accent-green" />
        <StatCard label="Unmeasured speed RMSE" value={summary ? summary.converged_speed_rmse.toExponential(1) : "—"} unit="rad/s" sub="reconstructed, never sensed" color="text-accent-blue" />
        <StatCard label="Innovation² (baseline)" value={summary ? summary.nis_baseline_mean.toFixed(1) : "—"} sub={`≈ ${summary?.n_measured ?? 0} measurements ⇒ consistent`} />
        <StatCard label="Anomaly" value={summary ? (summary.anomaly_detected ? "DETECTED" : "none") : "—"} sub={summary ? `peak innovation² ${summary.nis_anomaly_peak.toFixed(0)}` : ""} color={summary?.anomaly_detected ? "text-accent-red" : "text-text-muted"} />
      </div>

      <div className="flex items-center gap-3">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-wider">Observability</span>
        <div className="flex border border-border-strong">
          {(["full", "partial"] as Observability[]).map((o) => (
            <button
              key={o}
              onClick={() => setObs(o)}
              className={`font-mono text-[10px] px-3 py-1 uppercase tracking-wider transition-colors ${
                obs === o ? "bg-accent-blue text-white" : "text-text-muted hover:text-text-secondary"
              }`}
            >
              {o === "full" ? "Full (3/3 angles)" : "Partial (2/3 angles)"}
            </button>
          ))}
        </div>
        {loading && <LoadingNote text="running estimator…" />}
      </div>

      <ChartFrame title="Estimation error — twin vs physical plant (rad)">
        <ResponsiveContainer width="100%" height={150}>
          <LineChart data={chartData} margin={{ top: 6, right: 12, bottom: 0, left: 4 }}>
            <CartesianGrid stroke="#252830" vertical={false} />
            <XAxis dataKey="t" stroke="#464c58" tick={{ fontSize: 9, fontFamily: "monospace", fill: "#8a919e" }} tickFormatter={(v) => `${Number(v).toFixed(0)}s`} />
            <YAxis stroke="#464c58" tick={{ fontSize: 9, fontFamily: "monospace", fill: "#8a919e" }} width={48} tickFormatter={(v) => Number(v).toExponential(0)} />
            <Tooltip content={<TimeTooltip />} />
            <ReferenceLine y={SENSOR_NOISE_RAD} stroke="#f0a500" strokeDasharray="3 3" />
            {anomalyT != null && <ReferenceArea x1={anomalyT} x2={lastT} fill="#e53e3e" fillOpacity={0.08} />}
            <Line type="monotone" dataKey="angle_rmse" name="angle RMSE" stroke="#00c97a" dot={false} strokeWidth={1.5} isAnimationActive={!reduce} />
            <Line type="monotone" dataKey="speed_rmse" name="speed RMSE" stroke="#1a6cf5" dot={false} strokeWidth={1} isAnimationActive={!reduce} />
          </LineChart>
        </ResponsiveContainer>
        <Legend items={[["#00c97a", "angle RMSE"], ["#1a6cf5", "speed RMSE (unmeasured)"], ["#f0a500", "sensor noise"]]} />
      </ChartFrame>

      <ChartFrame title="Innovation² (anomaly score) — log scale">
        <ResponsiveContainer width="100%" height={150}>
          <LineChart data={chartData} margin={{ top: 6, right: 12, bottom: 0, left: 4 }}>
            <CartesianGrid stroke="#252830" vertical={false} />
            <XAxis dataKey="t" stroke="#464c58" tick={{ fontSize: 9, fontFamily: "monospace", fill: "#8a919e" }} tickFormatter={(v) => `${Number(v).toFixed(0)}s`} />
            <YAxis scale="log" domain={[0.3, "auto"]} allowDataOverflow stroke="#464c58" tick={{ fontSize: 9, fontFamily: "monospace", fill: "#8a919e" }} width={48} />
            <Tooltip content={<TimeTooltip />} />
            {summary && <ReferenceLine y={summary.nis_baseline_mean} stroke="#8a919e" strokeDasharray="3 3" />}
            {anomalyT != null && <ReferenceArea x1={anomalyT} x2={lastT} fill="#e53e3e" fillOpacity={0.08} />}
            <Line type="monotone" dataKey="nis" name="innovation²" stroke="#e53e3e" dot={false} strokeWidth={1.5} isAnimationActive={!reduce} />
          </LineChart>
        </ResponsiveContainer>
        <Legend items={[["#e53e3e", "innovation²"], ["#8a919e", "baseline (model fits)"], ["#e53e3e", "anomaly window"]]} />
      </ChartFrame>
    </div>
  );
}
