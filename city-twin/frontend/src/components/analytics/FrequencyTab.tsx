import { useEffect, useState } from "react";
import { useReducedMotion } from "framer-motion";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
} from "recharts";
import { API_BASE } from "../../hooks/useGridStream";
import type { FrequencyResponseRow } from "../../types/grid";
import { ChartFrame, LoadingNote } from "./shared";

const ROCOF_LIMIT = 1.0; // Hz/s grid-code limit

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function RocofTooltip({ active, payload }: any) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload as FrequencyResponseRow;
  return (
    <div className="bg-bg-elevated border border-border-strong px-2 py-1 font-mono text-[10px]">
      <div className="text-text-primary">{d.scenario}</div>
      <div className="text-text-secondary">RoCoF {d.rocof_hz_s.toFixed(2)} Hz/s · nadir {d.nadir_hz.toFixed(2)} Hz</div>
      <div className="text-text-muted">inertia H = {d.total_inertia_h}</div>
    </div>
  );
}

export default function FrequencyTab() {
  const reduce = useReducedMotion();
  const [rows, setRows] = useState<FrequencyResponseRow[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    setLoading(true);
    fetch(`${API_BASE}/frequency-response?disturbance=0.12`)
      .then((r) => r.json())
      .then((d: FrequencyResponseRow[]) => setRows(d))
      .catch(() => undefined)
      .finally(() => setLoading(false));
  }, []);

  const shortName = (s: string) =>
    s.includes("grid-forming") ? "Low + GFM" : s.includes("Low") ? "Low (renewables)" : "High (synchronous)";

  const chartData = rows.map((r) => ({ ...r, short: shortName(r.scenario) }));

  return (
    <div className="flex flex-col gap-4">
      <p className="font-mono text-[10px] text-text-secondary leading-relaxed">
        Inverter-coupled renewables carry no rotating inertia. As they displace synchronous
        machines, frequency falls faster after a loss — pushing RoCoF past the 1 Hz/s grid-code
        limit. <span className="text-accent-green">Grid-forming inverters</span> synthesize
        inertia and restore stability. (12% generation loss.)
      </p>

      {loading && <LoadingNote text="solving frequency response…" />}

      <ChartFrame title="Rate of Change of Frequency (RoCoF) by inertia regime">
        <ResponsiveContainer width="100%" height={170}>
          <BarChart data={chartData} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
            <CartesianGrid stroke="#252830" vertical={false} />
            <XAxis dataKey="short" stroke="#464c58" tick={{ fontSize: 9, fontFamily: "monospace", fill: "#8a919e" }} />
            <YAxis stroke="#464c58" tick={{ fontSize: 9, fontFamily: "monospace", fill: "#8a919e" }} width={36} unit=" " tickFormatter={(v) => v.toFixed(1)} />
            <Tooltip content={<RocofTooltip />} cursor={{ fill: "rgba(255,255,255,0.03)" }} />
            <ReferenceLine y={ROCOF_LIMIT} stroke="#f0a500" strokeDasharray="4 3" label={{ value: "1 Hz/s limit", fontSize: 9, fill: "#f0a500", position: "insideTopRight" }} />
            <Bar dataKey="rocof_hz_s" maxBarSize={56} isAnimationActive={!reduce}>
              {chartData.map((d) => (
                <Cell key={d.scenario} fill={d.breaches_rocof_limit ? "#e53e3e" : "#00c97a"} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </ChartFrame>

      <div className="border border-border-subtle bg-bg-tertiary overflow-hidden">
        <table className="w-full">
          <thead>
            <tr className="border-b border-border-subtle">
              {["Scenario", "Inertia H", "RoCoF", "Nadir", "Grid-code"].map((h) => (
                <th key={h} className="font-mono text-[9px] text-text-muted uppercase tracking-wider text-left px-3 py-1.5 font-normal">
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.scenario} className="border-b border-border-subtle/50">
                <td className="font-mono text-[10px] text-text-primary px-3 py-1.5">{r.scenario}</td>
                <td className="font-mono text-[10px] text-text-secondary px-3 py-1.5 tabular-nums">{r.total_inertia_h.toFixed(1)}</td>
                <td className={`font-mono text-[10px] px-3 py-1.5 tabular-nums ${r.breaches_rocof_limit ? "text-accent-red" : "text-accent-green"}`}>
                  {r.rocof_hz_s.toFixed(2)} Hz/s
                </td>
                <td className="font-mono text-[10px] text-text-secondary px-3 py-1.5 tabular-nums">{r.nadir_hz.toFixed(2)} Hz</td>
                <td className="px-3 py-1.5">
                  <span className={`font-mono text-[9px] uppercase tracking-wider px-1.5 py-0.5 border ${
                    r.breaches_rocof_limit ? "text-accent-red border-accent-red/40" : "text-accent-green border-accent-green/30"
                  }`}>
                    {r.breaches_rocof_limit ? "Breach" : "OK"}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > 0 && (
        <p className="font-mono text-[9px] text-text-muted">
          Initial RoCoF matches the analytical −ΔP/(2H) to{" "}
          {Math.max(...rows.map((r) => r.rocof_error_pct)).toFixed(2)}%.
        </p>
      )}
    </div>
  );
}
