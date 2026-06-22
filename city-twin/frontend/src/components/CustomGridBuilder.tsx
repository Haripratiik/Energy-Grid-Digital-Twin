import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "../hooks/useGridStream";

/**
 * Build-your-own-grid: assemble buses + lines, then Simulate runs a real AC
 * power flow on the backend (pandapower) and colours the result. The custom
 * grid is genuinely simulated and produces its own ontology (view it via the
 * "Custom" source in the Ontology panel).
 */

interface BBus {
  id: number;
  x: number;
  y: number;
  voltage_kv: number;
  load_mw: number;
  gen_mw: number;
  is_slack: boolean;
  name: string;
}
interface BLine { from_id: number; to_id: number; }

interface SimBus { id: number; vm_pu: number | null; va_deg: number | null; status: string; is_gen: boolean; is_slack: boolean; }
interface SimLine { from_id: number; to_id: number; kind: string; loading_pct: number; flow_mw: number; status: string; }
interface SimResult { converged: boolean; message: string; buses: SimBus[]; lines: SimLine[]; }

const VOLTAGES = [33, 132, 230, 400, 500];
const STATUS_COLOR: Record<string, string> = {
  NOMINAL: "#00c97a", DEGRADED: "#f0a500", CRITICAL: "#e53e3e", OVERLOADED: "#e53e3e",
  UNKNOWN: "#3b4050", // grid did not solve — render grey, never green
};
const TIER_COLOR = (kv: number) => (kv >= 300 ? "#a78bfa" : kv >= 100 ? "#60a5fa" : "#7b8696");

const STARTER: BBus[] = [
  { id: 1, x: 240, y: 300, voltage_kv: 230, load_mw: 0, gen_mw: 260, is_slack: true, name: "Plant" },
  { id: 2, x: 520, y: 180, voltage_kv: 132, load_mw: 120, gen_mw: 0, is_slack: false, name: "City A" },
  { id: 3, x: 520, y: 420, voltage_kv: 132, load_mw: 90, gen_mw: 0, is_slack: false, name: "City B" },
  { id: 4, x: 700, y: 300, voltage_kv: 132, load_mw: 0, gen_mw: 70, is_slack: false, name: "Wind" },
];
const STARTER_LINES: BLine[] = [
  { from_id: 1, to_id: 2 }, { from_id: 1, to_id: 3 }, { from_id: 2, to_id: 4 }, { from_id: 3, to_id: 4 },
];

function clamp(v: number, lo: number, hi: number) { return Math.max(lo, Math.min(hi, v)); }

export default function CustomGridBuilder() {
  const svgRef = useRef<SVGSVGElement>(null);
  const [buses, setBuses] = useState<BBus[]>(() => structuredClone(STARTER));
  const [lines, setLines] = useState<BLine[]>(() => structuredClone(STARTER_LINES));
  const [selected, setSelected] = useState<number | null>(null);
  const [connectMode, setConnectMode] = useState(false);
  const [connectFrom, setConnectFrom] = useState<number | null>(null);
  const [result, setResult] = useState<SimResult | null>(null);
  const [busy, setBusy] = useState(false);

  const dragRef = useRef<number | null>(null);
  const posOf = (id: number) => buses.find((b) => b.id === id);

  const toSvg = (cx: number, cy: number) => {
    const svg = svgRef.current;
    if (!svg) return { x: cx, y: cy };
    const pt = svg.createSVGPoint();
    pt.x = cx; pt.y = cy;
    const ctm = svg.getScreenCTM();
    if (!ctm) return { x: cx, y: cy };
    const p = pt.matrixTransform(ctm.inverse());
    return { x: p.x, y: p.y };
  };

  // drag (select mode only)
  useEffect(() => {
    const move = (e: MouseEvent) => {
      if (dragRef.current == null) return;
      const { x, y } = toSvg(e.clientX, e.clientY);
      setBuses((prev) => prev.map((b) =>
        b.id === dragRef.current ? { ...b, x: clamp(Math.round(x), 16, 884), y: clamp(Math.round(y), 16, 584) } : b));
    };
    const up = () => { dragRef.current = null; };
    window.addEventListener("mousemove", move);
    window.addEventListener("mouseup", up);
    return () => { window.removeEventListener("mousemove", move); window.removeEventListener("mouseup", up); };
  }, []);

  const simulate = useCallback(async () => {
    setBusy(true);
    try {
      const r = await fetch(`${API_BASE}/custom-grid/simulate`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          buses: buses.map((b) => ({
            id: b.id, voltage_kv: b.voltage_kv, load_mw: b.load_mw,
            gen_mw: b.gen_mw, is_slack: b.is_slack, name: b.name,
          })),
          lines,
        }),
      });
      setResult(await r.json());
    } catch {
      setResult({ converged: false, message: "Request failed.", buses: [], lines: [] });
    } finally {
      setBusy(false);
    }
  }, [buses, lines]);

  // simulate once on mount so the starter grid shows a result
  useEffect(() => { simulate(); /* eslint-disable-next-line */ }, []);

  const addBus = () => {
    const id = (buses.reduce((m, b) => Math.max(m, b.id), 0)) + 1;
    setBuses((prev) => [...prev, {
      id, x: 120 + ((id * 47) % 600), y: 90 + ((id * 83) % 380),
      voltage_kv: 132, load_mw: 20, gen_mw: 0, is_slack: false, name: `Bus ${id}`,
    }]);
    setSelected(id);
    setResult(null);
  };

  const deleteBus = (id: number) => {
    setBuses((prev) => prev.filter((b) => b.id !== id));
    setLines((prev) => prev.filter((l) => l.from_id !== id && l.to_id !== id));
    setSelected(null);
    setResult(null);
  };

  const patchBus = (id: number, patch: Partial<BBus>) => {
    setBuses((prev) => prev.map((b) => {
      if (b.id !== id) return patch.is_slack ? { ...b, is_slack: false } : b; // single slack
      return { ...b, ...patch };
    }));
    setResult(null);
  };

  const onBusClick = (id: number) => {
    if (connectMode) {
      if (connectFrom == null) { setConnectFrom(id); return; }
      if (connectFrom !== id) {
        setLines((prev) =>
          prev.some((l) => (l.from_id === connectFrom && l.to_id === id) || (l.from_id === id && l.to_id === connectFrom))
            ? prev : [...prev, { from_id: connectFrom, to_id: id }]);
        setResult(null);
      }
      setConnectFrom(null);
    } else {
      setSelected(id);
    }
  };

  const sel = selected != null ? buses.find((b) => b.id === selected) : undefined;
  const simBus = new Map((result?.buses ?? []).map((b) => [b.id, b]));
  const simLine = new Map((result?.lines ?? []).map((l) => [`${l.from_id}-${l.to_id}`, l]));
  const lineSim = (l: BLine) => simLine.get(`${l.from_id}-${l.to_id}`) ?? simLine.get(`${l.to_id}-${l.from_id}`);

  const overloaded = (result?.lines ?? []).filter((l) => l.status === "OVERLOADED").length;
  const unsolved = (result?.buses ?? []).filter((b) => b.status === "UNKNOWN").length;
  const worstV = (result?.buses ?? []).reduce((w, b) => Math.max(w, Math.abs((b.vm_pu ?? 1) - 1)), 0);

  return (
    <div className="flex h-full">
      <div className="flex-1 min-w-0 relative">
        <svg
          ref={svgRef}
          viewBox="0 0 900 600"
          preserveAspectRatio="xMidYMid meet"
          className="w-full h-full"
          style={{ background: "#0f1117" }}
          onClick={(e) => { if (e.target === svgRef.current) { setSelected(null); setConnectFrom(null); } }}
        >
          {/* lines */}
          {lines.map((l, i) => {
            const a = posOf(l.from_id); const b = posOf(l.to_id);
            if (!a || !b) return null;
            const s = lineSim(l);
            const color = s ? STATUS_COLOR[s.status] ?? "#3b4050" : "#3b4050";
            const w = s ? 1.5 + Math.min(s.loading_pct / 100, 1.2) * 2.5 : 1.5;
            return (
              <g key={i}>
                <line x1={a.x} y1={a.y} x2={b.x} y2={b.y} stroke={color} strokeWidth={w} strokeOpacity={0.85} />
                {s && (
                  <text x={(a.x + b.x) / 2} y={(a.y + b.y) / 2 - 3} textAnchor="middle"
                        fill="#8a919e" fontFamily="ui-monospace, monospace" fontSize="9">
                    {s.loading_pct.toFixed(0)}%{s.kind === "trafo" ? " ⛛" : ""}
                  </text>
                )}
              </g>
            );
          })}
          {/* buses */}
          {buses.map((b) => {
            const s = simBus.get(b.id);
            const color = s ? STATUS_COLOR[s.status] ?? TIER_COLOR(b.voltage_kv) : TIER_COLOR(b.voltage_kv);
            const r = b.gen_mw > 0 || b.is_slack ? 11 : 8;
            const isSel = selected === b.id;
            const isConnSrc = connectFrom === b.id;
            return (
              <g key={b.id}
                 style={{ cursor: connectMode ? "crosshair" : "grab" }}
                 onMouseDown={(e) => { e.stopPropagation(); if (!connectMode) { dragRef.current = b.id; setSelected(b.id); } }}
                 onClick={(e) => { e.stopPropagation(); onBusClick(b.id); }}>
                {(b.gen_mw > 0 || b.is_slack) && (
                  <circle cx={b.x} cy={b.y} r={r + 3} fill="none" stroke={color} strokeOpacity={0.4} strokeWidth={1} />
                )}
                <circle cx={b.x} cy={b.y} r={r}
                        fill={b.load_mw > 0 ? color : "#1d2128"} fillOpacity={b.load_mw > 0 ? 0.85 : 1}
                        stroke={isSel || isConnSrc ? "#5bbcff" : color} strokeWidth={isSel || isConnSrc ? 2.5 : 1.5} />
                {b.is_slack && (
                  <text x={b.x} y={b.y + 3.5} textAnchor="middle" fill="#0f1117" fontFamily="ui-monospace, monospace" fontSize="9" fontWeight={700}>S</text>
                )}
                <text x={b.x} y={b.y - r - 5} textAnchor="middle" fill="#9aa3b2" fontFamily="ui-monospace, monospace" fontSize="9">
                  {b.name || b.id}{s && s.vm_pu != null ? ` · ${s.vm_pu.toFixed(2)}pu` : ""}
                </text>
              </g>
            );
          })}
        </svg>

        <div className="absolute top-2 left-2 bg-[#0f1117]/85 backdrop-blur border border-[#2a2e38] px-2 py-1 rounded text-[9px] font-mono text-white/50">
          {connectMode
            ? (connectFrom == null ? "Connect: click the first bus" : "Connect: click the second bus")
            : "Drag to move · click to select · then Simulate"}
        </div>
        {result && (
          <div className={`absolute top-2 right-2 backdrop-blur border px-2 py-1 rounded text-[9px] font-mono ${
            !result.converged ? "bg-accent-red/10 border-accent-red/30 text-accent-red"
              : unsolved ? "bg-accent-yellow/10 border-accent-yellow/30 text-accent-yellow"
                         : "bg-accent-green/10 border-accent-green/30 text-accent-green"}`}>
            {result.converged
              ? `solved · ${overloaded} overloaded · worst |ΔV| ${(worstV * 100).toFixed(1)}%${unsolved ? ` · ${unsolved} unsolved` : ""}`
              : (result.message || "did not converge")}
          </div>
        )}
      </div>

      {/* sidebar */}
      <div className="w-56 shrink-0 border-l border-border-strong bg-bg-secondary flex flex-col overflow-y-auto">
        <div className="px-3 py-2 border-b border-border-strong">
          <div className="font-mono text-[10px] text-text-muted uppercase tracking-widest mb-2">Grid Builder</div>
          <div className="grid grid-cols-2 gap-1.5">
            <button onClick={addBus}
                    className="font-mono text-[9px] uppercase tracking-wide px-2 py-1.5 bg-bg-tertiary text-text-secondary border border-border-strong hover:bg-bg-elevated rounded">
              + Bus
            </button>
            <button onClick={() => { setConnectMode((m) => !m); setConnectFrom(null); }}
                    className={`font-mono text-[9px] uppercase tracking-wide px-2 py-1.5 border rounded transition-colors ${
                      connectMode ? "bg-accent-blue/20 text-accent-blue border-accent-blue/30"
                                  : "bg-bg-tertiary text-text-secondary border-border-strong hover:bg-bg-elevated"}`}>
              {connectMode ? "Connecting" : "+ Line"}
            </button>
          </div>
          <button onClick={simulate} disabled={busy}
                  className="w-full mt-1.5 font-mono text-[10px] uppercase tracking-wider px-2 py-1.5 bg-accent-green/20 text-accent-green border border-accent-green/40 hover:bg-accent-green/30 rounded disabled:opacity-40">
            {busy ? "Solving…" : "▶ Simulate (AC power flow)"}
          </button>
        </div>

        {sel ? (
          <div className="px-3 py-2 space-y-2 border-b border-border-strong">
            <div className="font-mono text-[10px] text-text-secondary">
              Bus <span className="text-accent-blue">{sel.id}</span>
            </div>
            <Field label="Name">
              <input value={sel.name} onChange={(e) => patchBus(sel.id, { name: e.target.value })}
                     className="w-full bg-bg-primary border border-border-strong text-text-primary text-[10px] font-mono px-1.5 py-1 rounded focus:outline-none focus:border-accent-blue" />
            </Field>
            <Field label="Voltage (kV)">
              <select value={sel.voltage_kv} onChange={(e) => patchBus(sel.id, { voltage_kv: Number(e.target.value) })}
                      className="w-full bg-bg-primary border border-border-strong text-text-primary text-[10px] font-mono px-1.5 py-1 rounded focus:outline-none focus:border-accent-blue">
                {VOLTAGES.map((v) => <option key={v} value={v}>{v} kV</option>)}
              </select>
            </Field>
            <Field label="Load (MW)">
              <input type="number" value={sel.load_mw} onChange={(e) => patchBus(sel.id, { load_mw: Math.max(0, Number(e.target.value)) })}
                     className="w-full bg-bg-primary border border-border-strong text-text-primary text-[10px] font-mono px-1.5 py-1 rounded focus:outline-none focus:border-accent-blue" />
            </Field>
            <Field label="Generation (MW)">
              <input type="number" value={sel.gen_mw} onChange={(e) => patchBus(sel.id, { gen_mw: Math.max(0, Number(e.target.value)) })}
                     className="w-full bg-bg-primary border border-border-strong text-text-primary text-[10px] font-mono px-1.5 py-1 rounded focus:outline-none focus:border-accent-blue" />
            </Field>
            <label className="flex items-center gap-1.5 font-mono text-[10px] text-text-secondary cursor-pointer">
              <input type="checkbox" checked={sel.is_slack} onChange={(e) => patchBus(sel.id, { is_slack: e.target.checked })} />
              Slack / reference bus
            </label>
            <button onClick={() => deleteBus(sel.id)}
                    className="w-full font-mono text-[9px] uppercase tracking-wide px-2 py-1 bg-accent-red/15 text-accent-red border border-accent-red/30 hover:bg-accent-red/25 rounded">
              Delete bus
            </button>
          </div>
        ) : (
          <div className="px-3 py-2 font-mono text-[9px] text-text-muted border-b border-border-strong">
            Click a bus to edit it, or "+ Bus" to add one. Mark one bus as Slack.
          </div>
        )}

        <div className="px-3 py-2 font-mono text-[9px] text-text-muted leading-relaxed">
          {buses.length} buses · {lines.length} lines<br />
          The custom grid is solved by a real AC power flow. View its ontology via
          the <span className="text-accent-blue">Custom</span> source in the Ontology panel.<br />
          <span className="text-text-muted/70">Honest: estimated line params (non-CEII); AC snapshot, not live swing dynamics.</span>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="font-mono text-[9px] text-text-muted uppercase">{label}</span>
      <div className="mt-0.5">{children}</div>
    </label>
  );
}
