import { Suspense, lazy, useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import type { GridState } from "../types/grid";
import FaultInjector from "./FaultInjector";
import CityMapView from "./CityMapView";
import CityMapEditor from "./CityMapEditor";
import { useCityMapPreset } from "../hooks/useCityMapPreset";

// Leaflet map is loaded only when the operator opens the Geographic view.
const GeoMap = lazy(() => import("./GeoMap"));

type ViewMode = "schematic" | "city" | "editor" | "geo";

interface Props {
  gridState: GridState | null;
  highlightedAsset: string | null;
  /** Show the fault-injection sandbox controls (testing mode only). */
  testingMode?: boolean;
}

/* ── layout: three concentric rings in an 800×600 viewBox ── */

const CX = 400;
const CY = 300;
const INNER_R = 80;
const MID_R = 180;
const OUTER_R = 280;
const INNER_N = 5;
const MID_N = 20;
const OUTER_N = 55;

interface NodePos {
  id: number;
  x: number;
  y: number;
  tier: 0 | 1 | 2;
}

/*
 * Bus ID → position mapping:
 *   1‑5   → 400 kV inner pentagon
 *   6‑25  → 132 kV middle ring
 *   26‑80 → 33 kV outer ring
 */
const POSITIONS: NodePos[] = [];
for (let i = 0; i < INNER_N; i++) {
  const a = (2 * Math.PI * i) / INNER_N - Math.PI / 2;
  POSITIONS.push({
    id: i + 1,
    x: CX + INNER_R * Math.cos(a),
    y: CY + INNER_R * Math.sin(a),
    tier: 0,
  });
}
for (let i = 0; i < MID_N; i++) {
  const a = (2 * Math.PI * i) / MID_N - Math.PI / 2;
  POSITIONS.push({
    id: INNER_N + i + 1,
    x: CX + MID_R * Math.cos(a),
    y: CY + MID_R * Math.sin(a),
    tier: 1,
  });
}
for (let i = 0; i < OUTER_N; i++) {
  const a = (2 * Math.PI * i) / OUTER_N - Math.PI / 2;
  POSITIONS.push({
    id: INNER_N + MID_N + i + 1,
    x: CX + OUTER_R * Math.cos(a),
    y: CY + OUTER_R * Math.sin(a),
    tier: 2,
  });
}
const POS = new Map(POSITIONS.map((p) => [p.id, p]));

/* ring‑adjacency edges (connect consecutive buses within each ring) */
interface RingEdge {
  from: number;
  to: number;
  tier: 0 | 1 | 2;
}
const RING_EDGES: RingEdge[] = [];
for (let i = 1; i <= INNER_N; i++)
  RING_EDGES.push({ from: i, to: i === INNER_N ? 1 : i + 1, tier: 0 });
for (let i = INNER_N + 1; i <= INNER_N + MID_N; i++)
  RING_EDGES.push({
    from: i,
    to: i === INNER_N + MID_N ? INNER_N + 1 : i + 1,
    tier: 1,
  });
const OS = INNER_N + MID_N + 1;
const OE = INNER_N + MID_N + OUTER_N;
for (let i = OS; i <= OE; i++)
  RING_EDGES.push({ from: i, to: i === OE ? OS : i + 1, tier: 2 });

/* ── colour / shape helpers ── */

const GEN_COLOR: Record<string, string> = {
  NUCLEAR: "#7c3aed",
  HYDRO: "#1a6cf5",
  WIND: "#00c97a",
  SOLAR: "#f0a500",
  GAS: "#e53e3e",
  THERMAL: "#f97316",
};

function hexPath(cx: number, cy: number, r: number): string {
  return (
    Array.from({ length: 6 }, (_, i) => {
      const a = (Math.PI / 3) * i - Math.PI / 6;
      return `${cx + r * Math.cos(a)},${cy + r * Math.sin(a)}`;
    }).reduce((s, p, i) => (i === 0 ? `M${p}` : `${s}L${p}`), "") + "Z"
  );
}

function diamondPath(cx: number, cy: number, r: number): string {
  return `M${cx},${cy - r}L${cx + r},${cy}L${cx},${cy + r}L${cx - r},${cy}Z`;
}

function loadingColor(pct: number): string {
  if (pct > 0.8) return "#e53e3e";
  if (pct > 0.6) return "#f0a500";
  return "#00c97a";
}

function statusOverride(
  status: string,
  base: string,
): [fill: string, opacity: number] {
  switch (status) {
    case "DEGRADED":
      return ["#f0a500", 0.75];
    case "CRITICAL":
      return ["#e53e3e", 0.85];
    case "TRIPPED":
      return ["#464c58", 0.3];
    default:
      return [base, 0.7];
  }
}

/* ── schematic view (original concentric rings) ── */

function SchematicView({
  gridState,
  highlightedAsset,
}: {
  gridState: GridState | null;
  highlightedAsset: string | null;
}) {
  const svgRef = useRef<SVGSVGElement>(null);
  const skelRef = useRef(false);
  const shapesRef = useRef(false);

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);

    /* ──── Phase 1: static SVG skeleton (once) ──── */
    if (!skelRef.current) {
      skelRef.current = true;

      const defs = svg.append("defs");
      const glow = defs
        .append("filter")
        .attr("id", "node-glow")
        .attr("x", "-50%")
        .attr("y", "-50%")
        .attr("width", "200%")
        .attr("height", "200%");
      glow
        .append("feGaussianBlur")
        .attr("stdDeviation", "4")
        .attr("result", "blur");
      const fm = glow.append("feMerge");
      fm.append("feMergeNode").attr("in", "blur");
      fm.append("feMergeNode").attr("in", "SourceGraphic");

      /* tier guide circles */
      const guides = svg.append("g").attr("class", "guides");
      [INNER_R, MID_R, OUTER_R].forEach((r) => {
        guides
          .append("circle")
          .attr("cx", CX)
          .attr("cy", CY)
          .attr("r", r)
          .attr("fill", "none")
          .attr("stroke", "#252830")
          .attr("stroke-width", 0.5)
          .attr("stroke-dasharray", "4 4");
      });
      const tierLabels: [number, string][] = [
        [INNER_R, "400 kV"],
        [MID_R, "132 kV"],
        [OUTER_R, "33 kV"],
      ];
      tierLabels.forEach(([r, text]) => {
        guides
          .append("text")
          .attr("x", CX + 6)
          .attr("y", CY - r - 8)
          .attr("text-anchor", "start")
          .attr("fill", "#464c58")
          .attr("font-family", "var(--font-mono)")
          .attr("font-size", "7px")
          .text(text);
      });

      svg.append("g").attr("class", "ring-edges");
      svg.append("g").attr("class", "trafo-edges");
      svg.append("g").attr("class", "nodes");
      svg.append("g").attr("class", "labels");

      /* ring edge lines */
      const edgesG = svg.select("g.ring-edges");
      RING_EDGES.forEach((e, idx) => {
        const a = POS.get(e.from)!;
        const b = POS.get(e.to)!;
        edgesG
          .append("line")
          .attr("class", `re-${idx}`)
          .attr("x1", a.x)
          .attr("y1", a.y)
          .attr("x2", b.x)
          .attr("y2", b.y)
          .attr("stroke", "#252830")
          .attr("stroke-width", 1)
          .attr("stroke-linecap", "round");
      });
    }

    if (!gridState) return;

    const genMap = new Map(gridState.generators.map((g) => [g.bus_id, g]));

    /* ──── Phase 2: create data‑driven shapes (once, on first state) ──── */
    if (!shapesRef.current) {
      shapesRef.current = true;
      const nodesG = svg.select("g.nodes");
      const labelsG = svg.select("g.labels");

      for (const bus of gridState.buses) {
        const p = POS.get(bus.id);
        if (!p) continue;

        const gen = genMap.get(bus.id);
        const isGen = gen != null;
        const gType = gen?.gen_type;
        const baseColor = isGen
          ? GEN_COLOR[gType!] ?? "#00c97a"
          : bus.power_load_mw > 5
            ? "#f0a500"
            : "#363b47";

        const isHex =
          isGen &&
          (gType === "NUCLEAR" ||
            gType === "HYDRO" ||
            gType === "GAS" ||
            gType === "THERMAL");
        const isDiamond = isGen && (gType === "WIND" || gType === "SOLAR");
        const r =
          p.tier === 0
            ? isGen
              ? 18
              : 14
            : p.tier === 1
              ? isGen
                ? 10
                : 7
              : isGen
                ? 7
                : 4;

        const g = nodesG.append("g").attr("class", `bus-${bus.id}`);

        if (isHex) {
          g.append("path")
            .attr("class", "shape")
            .attr("d", hexPath(p.x, p.y, r))
            .attr("fill", baseColor)
            .attr("fill-opacity", 0.7)
            .attr("stroke", baseColor)
            .attr("stroke-width", 1)
            .attr(
              "filter",
              gType === "NUCLEAR" ? "url(#node-glow)" : null as any,
            );
        } else if (isDiamond) {
          g.append("path")
            .attr("class", "shape")
            .attr("d", diamondPath(p.x, p.y, r))
            .attr("fill", baseColor)
            .attr("fill-opacity", 0.7)
            .attr("stroke", baseColor)
            .attr("stroke-width", 1);
        } else {
          g.append("circle")
            .attr("class", "shape")
            .attr("cx", p.x)
            .attr("cy", p.y)
            .attr("r", r)
            .attr("fill", baseColor)
            .attr("fill-opacity", bus.power_load_mw > 5 ? 0.5 : 0.25)
            .attr("stroke", bus.power_load_mw > 5 ? baseColor : "#363b47")
            .attr("stroke-width", p.tier === 0 ? 1.5 : 0.5);
        }

        if (p.tier <= 1) {
          const ly = isGen ? p.y - r - 6 : p.y + r + 10;
          const label = isGen ? `${gType!.slice(0, 3)} ${bus.id}` : `${bus.id}`;
          labelsG
            .append("text")
            .attr("class", `lbl-${bus.id}`)
            .attr("x", p.x)
            .attr("y", ly)
            .attr("text-anchor", "middle")
            .attr("fill", "#464c58")
            .attr("font-family", "var(--font-mono)")
            .attr("font-size", p.tier === 0 ? "8px" : "7px")
            .text(label);
        }
      }

      /* transformer connections */
      const trafoG = svg.select("g.trafo-edges");
      gridState.transformers.forEach((t, idx) => {
        const a = POS.get(t.from_bus);
        const b = POS.get(t.to_bus);
        if (!a || !b) return;
        trafoG
          .append("line")
          .attr("class", `tf-${idx}`)
          .attr("x1", a.x)
          .attr("y1", a.y)
          .attr("x2", b.x)
          .attr("y2", b.y)
          .attr("stroke", "#363b47")
          .attr("stroke-width", 1)
          .attr("stroke-linecap", "round");
        const mx = (a.x + b.x) / 2;
        const my = (a.y + b.y) / 2;
        trafoG
          .append("path")
          .attr("class", `tfd-${idx}`)
          .attr("d", diamondPath(mx, my, 3.5))
          .attr("fill", "#363b47")
          .attr("fill-opacity", 0.8);
      });
    }

    /* ──── Phase 3: attribute updates (every tick) ──── */
    const root = d3.select(svgRef.current);

    /* bus nodes */
    for (const bus of gridState.buses) {
      const p = POS.get(bus.id);
      if (!p) continue;
      const gen = genMap.get(bus.id);
      const isGen = gen != null;
      const baseColor = isGen
        ? GEN_COLOR[gen!.gen_type] ?? "#00c97a"
        : bus.power_load_mw > 5
          ? "#f0a500"
          : "#363b47";
      const [fill, opacity] = statusOverride(bus.status, baseColor);

      const shape = root.select(`g.bus-${bus.id} .shape`);
      shape
        .attr("fill", fill)
        .attr("fill-opacity", opacity)
        .attr("stroke", fill);
      shape.classed("pulse-red", bus.status === "CRITICAL");

      if (isGen && !gen!.online) {
        shape
          .attr("fill", "#464c58")
          .attr("fill-opacity", 0.3)
          .attr("stroke", "#464c58");
      }
    }

    /* ring edges — distribute line state by voltage tier */
    const linesByTier = [
      gridState.lines.filter((l) => l.voltage_kv >= 300),
      gridState.lines.filter(
        (l) => l.voltage_kv >= 100 && l.voltage_kv < 300,
      ),
      gridState.lines.filter((l) => l.voltage_kv < 100),
    ];
    const tierCtr = [0, 0, 0];

    RING_EDGES.forEach((e, idx) => {
      const tier = e.tier;
      const tLines = linesByTier[tier];
      const li = tLines.length > 0 ? tierCtr[tier] % tLines.length : -1;
      tierCtr[tier]++;
      const el = root.select(`line.re-${idx}`);
      const line = li >= 0 ? tLines[li] : null;

      if (line?.tripped) {
        el.attr("stroke", "#464c58")
          .attr("stroke-width", 1)
          .attr("stroke-dasharray", "3 2")
          .attr("opacity", 0.3)
          .classed("flow-animation", false);
      } else if (line) {
        const pct = line.flow_pct_of_limit;
        el.attr("stroke", loadingColor(pct))
          .attr("stroke-width", 1 + 3 * pct)
          .attr("stroke-dasharray", pct > 0.05 ? "8 4" : "none")
          .attr("opacity", 0.7)
          .classed("flow-animation", pct > 0.05);
      } else {
        el.attr("stroke", "#252830")
          .attr("stroke-width", 1)
          .attr("stroke-dasharray", "none")
          .attr("opacity", 0.5)
          .classed("flow-animation", false);
      }
    });

    /* transformer edges */
    gridState.transformers.forEach((t, idx) => {
      const loading = t.loading_pct / 100;
      const color =
        t.status === "TRIPPED" ? "#464c58" : loadingColor(loading);
      const op = t.status === "TRIPPED" ? 0.3 : 0.8;
      root
        .select(`line.tf-${idx}`)
        .attr("stroke", color)
        .attr("stroke-width", 1 + 2 * loading)
        .attr("opacity", op);
      root
        .select(`path.tfd-${idx}`)
        .attr("fill", color)
        .attr("fill-opacity", op);
    });

    /* highlight selected asset */
    root.selectAll(".asset-highlight").remove();
    if (highlightedAsset) {
      const parts = highlightedAsset.split(".");
      const idNum = parseInt(parts[parts.length - 1]);
      if (!isNaN(idNum) && POS.has(idNum)) {
        const p = POS.get(idNum)!;
        root
          .select("g.nodes")
          .append("circle")
          .attr("class", "asset-highlight")
          .attr("cx", p.x)
          .attr("cy", p.y)
          .attr("r", p.tier === 0 ? 24 : p.tier === 1 ? 14 : 10)
          .attr("fill", "none")
          .attr("stroke", "#5bbcff")
          .attr("stroke-width", 2)
          .attr("stroke-dasharray", "4 3")
          .attr("opacity", 0.8);
      }
    }
  }, [gridState, highlightedAsset]);

  return (
    <div className="flex-1 flex items-center justify-center bg-bg-primary p-1">
      <svg
        ref={svgRef}
        viewBox="0 0 800 600"
        className="w-full h-full"
        style={{ background: "transparent" }}
      />
    </div>
  );
}

/* ── main component with view toggle ── */

export default function GridTopology({ gridState, highlightedAsset, testingMode = true }: Props) {
  const [view, setView] = useState<ViewMode>("schematic");
  const presetCtx = useCityMapPreset();

  const tabCls = (id: ViewMode) =>
    `font-mono text-[9px] px-2 py-0.5 uppercase tracking-wide transition-colors ${
      view === id
        ? "bg-accent-blue/20 text-accent-blue border border-accent-blue/30"
        : "text-text-muted hover:text-text-secondary border border-transparent"
    }`;

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-1.5 border-b border-border-strong bg-bg-tertiary flex items-center justify-between">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          <span className="text-accent-blue">01</span> Grid Twin · Topology
        </span>
        <div className="flex items-center gap-0.5">
          <button onClick={() => setView("schematic")} className={tabCls("schematic")}>
            Schematic
          </button>
          <button onClick={() => setView("city")} className={tabCls("city")}>
            City Map
          </button>
          <button onClick={() => setView("editor")} className={tabCls("editor")}>
            Edit Layout
          </button>
          <button onClick={() => setView("geo")} className={tabCls("geo")}>
            Geographic
          </button>
        </div>
        {view === "city" && (
          <select
            value={presetCtx.presetId}
            onChange={(e) => presetCtx.switchPreset(e.target.value)}
            className="ml-2 bg-bg-secondary text-text-secondary border border-border-strong text-[9px] font-mono px-1.5 py-0.5 rounded"
          >
            {presetCtx.allPresets.map((p) => (
              <option key={p.id} value={p.id}>{p.name}</option>
            ))}
          </select>
        )}
      </div>

      {view === "geo" ? (
        <div className="flex-1 min-h-0 bg-bg-primary">
          <Suspense
            fallback={
              <div className="flex h-full items-center justify-center font-mono text-[11px] text-text-muted">
                loading map…
              </div>
            }
          >
            <GeoMap gridState={gridState} />
          </Suspense>
        </div>
      ) : view === "schematic" ? (
        <SchematicView gridState={gridState} highlightedAsset={highlightedAsset} />
      ) : view === "editor" ? (
        <div className="flex-1 min-h-0 bg-bg-primary">
          <CityMapEditor presetCtx={presetCtx} />
        </div>
      ) : (
        <div className="flex-1 min-h-0 bg-bg-primary">
          <CityMapView
            gridState={gridState}
            highlightedAsset={highlightedAsset}
            buses={presetCtx.preset.buses}
            districts={presetCtx.preset.districts}
            riverPath={presetCtx.preset.riverPath}
            revision={presetCtx.revision}
          />
        </div>
      )}

      {testingMode && <FaultInjector />}
    </div>
  );
}
