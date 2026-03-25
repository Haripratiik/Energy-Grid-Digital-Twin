import { useMemo } from "react";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Cell,
} from "recharts";
import type { GeneratorState } from "../types/grid";

interface Props {
  generators: GeneratorState[];
  totalLoad: number;
}

type GenType = GeneratorState["gen_type"];

const TYPE_COLOR: Record<GenType, string> = {
  NUCLEAR: "#7c3aed",
  HYDRO: "#1a6cf5",
  WIND: "#00c97a",
  SOLAR: "#f0a500",
  GAS: "#e53e3e",
  THERMAL: "#f97316",
};

const TYPE_ORDER: GenType[] = [
  "NUCLEAR",
  "HYDRO",
  "WIND",
  "SOLAR",
  "GAS",
  "THERMAL",
];

interface GenBucket {
  type: GenType;
  totalMw: number;
  capacityMw: number;
  onlineCount: number;
  totalCount: number;
}

function CustomTooltip({
  active,
  payload,
}: {
  active?: boolean;
  payload?: Array<{ payload: { type: string; totalMw: number; capacityMw: number } }>;
}) {
  if (!active || !payload?.[0]) return null;
  const d = payload[0].payload;
  return (
    <div className="bg-bg-elevated border border-border-subtle p-2 font-mono text-[10px]">
      <div className="text-text-primary">{d.type}</div>
      <div className="text-text-secondary">
        {d.totalMw.toFixed(1)} / {d.capacityMw.toFixed(1)} MW
      </div>
    </div>
  );
}

export default function GeneratorMix({ generators, totalLoad }: Props) {
  const buckets = useMemo<GenBucket[]>(() => {
    const map = new Map<GenType, GenBucket>();
    for (const t of TYPE_ORDER) {
      map.set(t, { type: t, totalMw: 0, capacityMw: 0, onlineCount: 0, totalCount: 0 });
    }
    for (const g of generators) {
      let b = map.get(g.gen_type);
      if (!b) {
        b = {
          type: g.gen_type,
          totalMw: 0,
          capacityMw: 0,
          onlineCount: 0,
          totalCount: 0,
        };
        map.set(g.gen_type, b);
      }
      b.capacityMw += g.capacity_mw;
      b.totalCount += 1;
      if (g.online) {
        b.totalMw += g.electrical_power_mw;
        b.onlineCount += 1;
      }
    }
    return TYPE_ORDER.map((t) => map.get(t)!).filter((b) => b.totalCount > 0);
  }, [generators]);

  const totalGen = buckets.reduce((s, b) => s + b.totalMw, 0);

  const chartData = buckets.map((b) => ({
    type: b.type,
    totalMw: b.totalMw,
    capacityMw: b.capacityMw,
  }));

  return (
    <div className="flex flex-col h-full">
      {/* header */}
      <div className="px-3 py-1.5 border-b border-border-strong bg-bg-tertiary">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          Generation Mix
        </span>
      </div>

      {/* chart */}
      <div className="px-3 pt-3" style={{ height: 80 }}>
        <ResponsiveContainer width="100%" height="100%">
          <BarChart
            data={chartData}
            layout="vertical"
            margin={{ top: 0, right: 0, bottom: 0, left: 0 }}
            barCategoryGap={2}
          >
            <XAxis type="number" hide />
            <YAxis type="category" dataKey="type" hide />
            <Tooltip
              content={<CustomTooltip />}
              cursor={{ fill: "rgba(255,255,255,0.03)" }}
            />
            <Bar dataKey="totalMw" radius={0} maxBarSize={14}>
              {chartData.map((entry) => (
                <Cell
                  key={entry.type}
                  fill={TYPE_COLOR[entry.type as GenType] ?? "#555"}
                />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* summary table */}
      <div className="flex-1 overflow-y-auto px-3 pb-2 pt-1">
        <table className="w-full">
          <thead>
            <tr>
              {["Type", "MW", "Cap", "Online"].map((h) => (
                <th
                  key={h}
                  className="font-mono text-[9px] text-text-muted uppercase tracking-wider text-left pb-1 font-normal"
                >
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {buckets.map((b) => (
              <tr key={b.type}>
                <td className="py-0.5 pr-2">
                  <span className="flex items-center gap-1.5">
                    <span
                      className="inline-block w-2 h-2"
                      style={{ background: TYPE_COLOR[b.type] }}
                    />
                    <span className="font-mono text-[10px] text-text-primary">
                      {b.type}
                    </span>
                  </span>
                </td>
                <td className="font-mono text-[10px] text-text-secondary py-0.5">
                  {b.totalMw.toFixed(1)}
                </td>
                <td className="font-mono text-[10px] text-text-muted py-0.5">
                  {b.capacityMw.toFixed(1)}
                </td>
                <td className="font-mono text-[10px] text-text-secondary py-0.5">
                  {b.onlineCount}/{b.totalCount}
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {/* totals */}
        <div className="mt-2 pt-2 border-t border-border-subtle flex items-center justify-between">
          <span className="font-mono text-[10px] text-text-muted uppercase tracking-wide">
            Gen / Load
          </span>
          <span className="font-mono text-[11px] text-text-primary">
            <span
              className={
                totalGen >= totalLoad ? "text-accent-green" : "text-accent-red"
              }
            >
              {totalGen.toFixed(1)}
            </span>
            <span className="text-text-muted"> / </span>
            {totalLoad.toFixed(1)} MW
          </span>
        </div>
      </div>
    </div>
  );
}
