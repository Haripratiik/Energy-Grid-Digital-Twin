import { useCallback, useEffect, useState } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
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
import { API_BASE } from "../hooks/useGridStream";
import type { LodfBenchRow, TwinRunResponse } from "../types/grid";

interface Props {
  open: boolean;
  onClose: () => void;
}

type Observability = "full" | "partial";
const MEASURED: Record<Observability, string> = { full: "0,1,2", partial: "0,2" };

const SENSOR_NOISE_RAD = 0.01;

function StatCard({
  label,
  value,
  unit,
  sub,
  color,
}: {
  label: string;
  value: string;
  unit?: string;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5 px-3 py-2 bg-bg-tertiary border border-border-subtle">
      <span className="font-mono text-[9px] text-text-muted uppercase tracking-widest">
        {label}
      </span>
      <span className={`font-mono text-lg font-bold tabular-nums leading-none ${color ?? "text-text-primary"}`}>
        {value}
        {unit && <span className="text-[11px] text-text-muted ml-1 font-normal">{unit}</span>}
      </span>
      {sub && <span className="font-mono text-[9px] text-text-secondary">{sub}</span>}
    </div>
  );
}

function ChartTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="bg-bg-elevated border border-border-strong px-2 py-1 font-mono text-[10px]">
      <div className="text-text-muted">t = {Number(label).toFixed(2)} s</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} style={{ color: p.color }}>
          {p.name}: {Number(p.value).toExponential(2)}
        </div>
      ))}
    </div>
  );
}

function PerfStrip() {
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

  useEffect(() => {
    run(caseId);
  }, [caseId, run]);

  const cases = [
    { id: "ieee118", label: "IEEE-118" },
    { id: "case300", label: "300-bus" },
    { id: "case1354", label: "1354-bus" },
    { id: "case2869", label: "2869-bus" },
  ];

  return (
    <div className="border border-border-subtle bg-bg-tertiary">
      <div className="px-3 py-1.5 border-b border-border-subtle flex items-center justify-between">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          Fast N-1 Screening · LODF vs brute force
        </span>
        <div className="flex gap-1">
          {cases.map((c) => (
            <button
              key={c.id}
              onClick={() => setCaseId(c.id)}
              className={`font-mono text-[9px] px-1.5 py-0.5 uppercase tracking-wider border transition-colors ${
                caseId === c.id
                  ? "border-accent-blue text-accent-blue"
                  : "border-border-subtle text-text-muted hover:text-text-secondary"
              }`}
            >
              {c.label}
            </button>
          ))}
        </div>
      </div>
      <div className="grid grid-cols-4 divide-x divide-border-subtle">
        <Metric label="Branches" value={busy ? "…" : String(row?.n_branch ?? "—")} />
        <Metric
          label="LODF screen"
          value={busy ? "…" : row ? row.lodf_screen_ms.toFixed(2) : "—"}
          unit="ms"
          color="text-accent-green"
        />
        <Metric
          label="Speedup"
          value={busy ? "…" : row ? `${row.speedup.toFixed(0)}×` : "—"}
          color="text-accent-blue"
        />
        <Metric
          label="Screen rate"
          value={busy ? "…" : row ? Math.round(row.contingencies_per_s).toLocaleString() : "—"}
          unit="/s"
        />
      </div>
    </div>
  );
}

function Metric({ label, value, unit, color }: { label: string; value: string; unit?: string; color?: string }) {
  return (
    <div className="flex flex-col px-3 py-2">
      <span className="font-mono text-[9px] text-text-muted uppercase tracking-wider">{label}</span>
      <span className={`font-mono text-[15px] font-bold tabular-nums leading-tight ${color ?? "text-text-primary"}`}>
        {value}
        {unit && <span className="text-[10px] text-text-muted ml-0.5 font-normal">{unit}</span>}
      </span>
    </div>
  );
}

export default function TwinView({ open, onClose }: Props) {
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

  useEffect(() => {
    if (open) run(obs);
  }, [open, obs, run]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  const summary = data?.summary;
  const anomalyT =
    data?.anomaly_step != null ? data.anomaly_step * data.dt_s : null;
  const lastT = data?.steps.length ? data.steps[data.steps.length - 1].t : 0;
  const chartData = data?.steps ?? [];

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60 p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          onClick={onClose}
        >
          <motion.div
            className="w-full max-w-5xl max-h-[92vh] overflow-y-auto bg-bg-secondary border border-border-strong shadow-2xl"
            initial={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.97, y: 8 }}
            animate={reduce ? { opacity: 1 } : { opacity: 1, scale: 1, y: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.98 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* header */}
            <div className="sticky top-0 z-10 flex items-center justify-between px-4 py-3 border-b border-border-strong bg-bg-secondary">
              <div>
                <h2 className="font-mono text-[13px] text-text-primary tracking-wide">
                  Digital Twin · Real-Time State Estimation
                </h2>
                <p className="font-mono text-[10px] text-text-muted mt-0.5">
                  Unscented Kalman Filter tracking a noisy physical plant (IEEE-9, 3 machines)
                </p>
              </div>
              <button
                onClick={onClose}
                aria-label="Close digital twin view"
                className="font-mono text-[11px] px-2 py-1 border border-border-strong text-text-secondary hover:bg-bg-elevated transition-colors"
              >
                ESC ✕
              </button>
            </div>

            <div className="p-4 flex flex-col gap-4">
              {/* stat cards */}
              <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
                <StatCard
                  label="Angle RMSE"
                  value={summary ? summary.converged_angle_rmse.toExponential(1) : "—"}
                  unit="rad"
                  sub={`sensor noise ${SENSOR_NOISE_RAD} — filter denoises`}
                  color="text-accent-green"
                />
                <StatCard
                  label="Unmeasured speed RMSE"
                  value={summary ? summary.converged_speed_rmse.toExponential(1) : "—"}
                  unit="rad/s"
                  sub="reconstructed, never sensed"
                  color="text-accent-blue"
                />
                <StatCard
                  label="Innovation² (baseline)"
                  value={summary ? summary.nis_baseline_mean.toFixed(1) : "—"}
                  sub={`≈ ${summary?.n_measured ?? 0} measurements ⇒ consistent`}
                />
                <StatCard
                  label="Anomaly"
                  value={summary ? (summary.anomaly_detected ? "DETECTED" : "none") : "—"}
                  sub={summary ? `peak innovation² ${summary.nis_anomaly_peak.toFixed(0)}` : ""}
                  color={summary?.anomaly_detected ? "text-accent-red" : "text-text-muted"}
                />
              </div>

              {/* observability toggle */}
              <div className="flex items-center gap-3">
                <span className="font-mono text-[10px] text-text-muted uppercase tracking-wider">
                  Observability
                </span>
                <div className="flex border border-border-strong">
                  {(["full", "partial"] as Observability[]).map((o) => (
                    <button
                      key={o}
                      onClick={() => setObs(o)}
                      className={`font-mono text-[10px] px-3 py-1 uppercase tracking-wider transition-colors ${
                        obs === o
                          ? "bg-accent-blue text-white"
                          : "text-text-muted hover:text-text-secondary"
                      }`}
                    >
                      {o === "full" ? "Full (3/3 angles)" : "Partial (2/3 angles)"}
                    </button>
                  ))}
                </div>
                {loading && (
                  <span className="font-mono text-[10px] text-accent-yellow animate-pulse">
                    running estimator…
                  </span>
                )}
              </div>

              {/* tracking-error chart */}
              <ChartFrame title="Estimation error — twin vs physical plant (rad)">
                <ResponsiveContainer width="100%" height={150}>
                  <LineChart data={chartData} margin={{ top: 6, right: 12, bottom: 0, left: 4 }}>
                    <CartesianGrid stroke="#252830" vertical={false} />
                    <XAxis
                      dataKey="t"
                      stroke="#464c58"
                      tick={{ fontSize: 9, fontFamily: "monospace", fill: "#8a919e" }}
                      tickFormatter={(v) => `${Number(v).toFixed(0)}s`}
                    />
                    <YAxis
                      stroke="#464c58"
                      tick={{ fontSize: 9, fontFamily: "monospace", fill: "#8a919e" }}
                      width={48}
                      tickFormatter={(v) => Number(v).toExponential(0)}
                    />
                    <Tooltip content={<ChartTooltip />} />
                    <ReferenceLine y={SENSOR_NOISE_RAD} stroke="#f0a500" strokeDasharray="3 3" />
                    {anomalyT != null && (
                      <ReferenceArea x1={anomalyT} x2={lastT} fill="#e53e3e" fillOpacity={0.08} />
                    )}
                    <Line type="monotone" dataKey="angle_rmse" name="angle RMSE" stroke="#00c97a" dot={false} strokeWidth={1.5} isAnimationActive={!reduce} />
                    <Line type="monotone" dataKey="speed_rmse" name="speed RMSE" stroke="#1a6cf5" dot={false} strokeWidth={1} isAnimationActive={!reduce} />
                  </LineChart>
                </ResponsiveContainer>
                <Legend items={[["#00c97a", "angle RMSE"], ["#1a6cf5", "speed RMSE (unmeasured)"], ["#f0a500", "sensor noise"]]} />
              </ChartFrame>

              {/* innovation chart */}
              <ChartFrame title="Innovation² (anomaly score) — log scale">
                <ResponsiveContainer width="100%" height={150}>
                  <LineChart data={chartData} margin={{ top: 6, right: 12, bottom: 0, left: 4 }}>
                    <CartesianGrid stroke="#252830" vertical={false} />
                    <XAxis
                      dataKey="t"
                      stroke="#464c58"
                      tick={{ fontSize: 9, fontFamily: "monospace", fill: "#8a919e" }}
                      tickFormatter={(v) => `${Number(v).toFixed(0)}s`}
                    />
                    <YAxis
                      scale="log"
                      domain={[0.3, "auto"]}
                      allowDataOverflow
                      stroke="#464c58"
                      tick={{ fontSize: 9, fontFamily: "monospace", fill: "#8a919e" }}
                      width={48}
                    />
                    <Tooltip content={<ChartTooltip />} />
                    {summary && (
                      <ReferenceLine y={summary.nis_baseline_mean} stroke="#8a919e" strokeDasharray="3 3" />
                    )}
                    {anomalyT != null && (
                      <ReferenceArea x1={anomalyT} x2={lastT} fill="#e53e3e" fillOpacity={0.08} />
                    )}
                    <Line type="monotone" dataKey="nis" name="innovation²" stroke="#e53e3e" dot={false} strokeWidth={1.5} isAnimationActive={!reduce} />
                  </LineChart>
                </ResponsiveContainer>
                <Legend items={[["#e53e3e", "innovation²"], ["#8a919e", "baseline (model fits)"], ["#e53e3e", "anomaly window"]]} />
              </ChartFrame>

              {/* performance highlight */}
              <PerfStrip />
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}

function ChartFrame({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="border border-border-subtle bg-bg-tertiary">
      <div className="px-3 py-1.5 border-b border-border-subtle">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">{title}</span>
      </div>
      <div className="p-2">{children}</div>
    </div>
  );
}

function Legend({ items }: { items: [string, string][] }) {
  return (
    <div className="flex flex-wrap gap-3 px-2 pb-1">
      {items.map(([color, label]) => (
        <span key={label} className="flex items-center gap-1.5 font-mono text-[9px] text-text-secondary">
          <span className="inline-block w-2.5 h-[2px]" style={{ background: color }} />
          {label}
        </span>
      ))}
    </div>
  );
}
