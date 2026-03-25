import { useEffect, useRef, useState, useCallback } from "react";
import * as d3 from "d3";
import type { GridState } from "../types/grid";
import type { BusGeo, DistrictRegion } from "../data/presets";

interface Props {
  gridState: GridState | null;
  highlightedAsset: string | null;
  buses: BusGeo[];
  districts: DistrictRegion[];
  riverPath: string;
  /** Increment to force a full SVG rebuild (e.g. after preset switch). */
  revision?: number;
}

const GEN_COLOR: Record<string, string> = {
  NUCLEAR: "#a78bfa",
  HYDRO: "#60a5fa",
  WIND: "#34d399",
  SOLAR: "#fbbf24",
  GAS: "#f87171",
  THERMAL: "#fb923c",
};

const VOLTAGE_TIER = (kv: number) => (kv >= 300 ? 0 : kv >= 100 ? 1 : 2);

function loadingColor(pct: number): string {
  if (pct > 0.8) return "#f87171";
  if (pct > 0.6) return "#fbbf24";
  return "#34d399";
}

interface Tooltip {
  x: number;
  y: number;
  name: string;
  busId: number;
  voltage: string;
  genMw: number;
  loadMw: number;
  status: string;
  genType?: string;
}

const KNOWN_EDGES: [number, number][] = [
  [1,2],[2,3],[3,4],[4,5],[5,1],[1,3],[2,4],[2,5],
  [6,7],[7,8],[8,9],[9,10],[10,11],[11,12],[12,13],
  [13,14],[14,15],[15,16],[16,17],[17,18],[18,19],[19,20],[20,21],
  [21,22],[22,23],[23,24],[24,25],[25,6],
  [6,9],[8,11],[10,14],[16,20],[17,25],
  [26,27],[27,28],[28,29],[29,30],[30,31],[31,32],[32,33],
  [33,34],[34,35],[35,36],[36,37],[37,38],[38,39],[39,40],
  [40,41],[41,42],[42,43],[43,44],[44,45],[45,46],[46,47],
  [47,48],[48,49],[49,50],[50,51],[51,52],[52,53],[53,54],
  [54,55],[55,56],[56,57],[57,58],[58,59],[59,60],[60,61],
  [61,62],[62,63],[63,64],[64,65],[65,66],[66,67],[67,68],
  [68,69],[69,70],
  [71,26],[71,35],[72,40],[72,47],[73,51],[73,60],
  [74,64],[74,70],[75,76],[76,77],[77,78],[78,79],[79,80],[75,80],
];

function buildRoads(buses: BusGeo[]): string[] {
  if (buses.length === 0) return [];
  const xs = buses.map((b) => b.x);
  const ys = buses.map((b) => b.y);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const mx = (xMin + xMax) / 2, my = (yMin + yMax) / 2;
  return [
    `M ${xMin - 30},${my} H ${xMax + 30}`,
    `M ${mx},${yMin - 20} V ${yMax + 20}`,
    `M ${xMin - 30},${my - 120} H ${xMax + 30}`,
    `M ${xMin - 30},${my + 120} H ${xMax + 30}`,
    `M ${mx - 150},${yMin - 20} V ${yMax + 20}`,
    `M ${mx + 150},${yMin - 20} V ${yMax + 20}`,
  ];
}

function buildBlockAreas(buses: BusGeo[]): { x: number; y: number; w: number; h: number }[] {
  const districtClusters = new Map<string, { xs: number[]; ys: number[] }>();
  for (const b of buses) {
    const key = b.district.toLowerCase();
    if (key.includes("jct") || key.includes("junction")) continue;
    if (!districtClusters.has(key)) districtClusters.set(key, { xs: [], ys: [] });
    const c = districtClusters.get(key)!;
    c.xs.push(b.x);
    c.ys.push(b.y);
  }
  const areas: { x: number; y: number; w: number; h: number }[] = [];
  for (const [, c] of districtClusters) {
    if (c.xs.length < 1) continue;
    const cx = c.xs.reduce((a, b) => a + b, 0) / c.xs.length;
    const cy = c.ys.reduce((a, b) => a + b, 0) / c.ys.length;
    areas.push({ x: cx - 35, y: cy - 25, w: 70, h: 50 });
  }
  return areas.slice(0, 12);
}

export default function CityMapView({
  gridState,
  highlightedAsset,
  buses,
  districts,
  riverPath,
  revision = 0,
}: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const rootGRef = useRef<SVGGElement | null>(null);
  const builtRevision = useRef(-1);
  const [tooltip, setTooltip] = useState<Tooltip | null>(null);

  const busGeoMap = useRef(new Map<number, BusGeo>());

  const hideTooltip = useCallback(() => setTooltip(null), []);

  // Rebuild static SVG layers when preset changes
  useEffect(() => {
    if (!svgRef.current || !containerRef.current) return;
    const svg = d3.select(svgRef.current);

    // Full teardown on revision change
    if (builtRevision.current !== revision) {
      svg.selectAll("*").remove();
      rootGRef.current = null;
    }

    if (rootGRef.current) return;
    builtRevision.current = revision;

    busGeoMap.current = new Map(buses.map((b) => [b.id, b]));

    const root = svg.append("g").attr("class", "map-root");
    rootGRef.current = root.node();

    const defs = svg.append("defs");
    const glow = defs
      .append("filter")
      .attr("id", "node-glow")
      .attr("x", "-80%").attr("y", "-80%")
      .attr("width", "260%").attr("height", "260%");
    glow.append("feGaussianBlur").attr("stdDeviation", "3").attr("result", "blur");
    const merge = glow.append("feMerge");
    merge.append("feMergeNode").attr("in", "blur");
    merge.append("feMergeNode").attr("in", "SourceGraphic");

    root.append("rect")
      .attr("x", 0).attr("y", 0)
      .attr("width", 900).attr("height", 700)
      .attr("fill", "#0f1117");

    // Roads
    const roadsG = root.append("g").attr("class", "roads");
    buildRoads(buses).forEach((d) => {
      roadsG.append("path").attr("d", d)
        .attr("fill", "none").attr("stroke", "#1e2028")
        .attr("stroke-width", 8).attr("stroke-linecap", "round");
      roadsG.append("path").attr("d", d)
        .attr("fill", "none").attr("stroke", "#262a35")
        .attr("stroke-width", 1).attr("stroke-dasharray", "8 12")
        .attr("stroke-linecap", "round");
    });

    // River
    if (riverPath) {
      root.append("path").attr("d", riverPath)
        .attr("fill", "none").attr("stroke", "#1e3a5f")
        .attr("stroke-width", 18).attr("stroke-linecap", "round")
        .attr("stroke-linejoin", "round").attr("opacity", 0.4);
      root.append("path").attr("d", riverPath)
        .attr("fill", "none").attr("stroke", "#2563eb")
        .attr("stroke-width", 4).attr("stroke-linecap", "round")
        .attr("opacity", 0.2);
    }

    // Districts
    const distG = root.append("g").attr("class", "districts");
    districts.forEach((d) => {
      distG.append("polygon")
        .attr("points", d.points.map((p) => p.join(",")).join(" "))
        .attr("fill", d.color).attr("fill-opacity", 0.05)
        .attr("stroke", d.color).attr("stroke-opacity", 0.15)
        .attr("stroke-width", 1).attr("stroke-dasharray", "4 2");
      const cx = d.points.reduce((s, p) => s + p[0], 0) / d.points.length;
      const cy = d.points.reduce((s, p) => s + p[1], 0) / d.points.length;
      distG.append("text")
        .attr("x", cx).attr("y", cy)
        .attr("text-anchor", "middle").attr("dominant-baseline", "central")
        .attr("fill", d.color).attr("fill-opacity", 0.3)
        .attr("font-family", "ui-sans-serif, system-ui, sans-serif")
        .attr("font-size", "10px").attr("font-weight", "600")
        .attr("letter-spacing", "0.5px").text(d.name);
    });

    // Building blocks
    const blocksG = root.append("g").attr("class", "blocks");
    buildBlockAreas(buses).forEach((area) => {
      for (let bx = area.x; bx < area.x + area.w; bx += 16) {
        for (let by = area.y; by < area.y + area.h; by += 12) {
          blocksG.append("rect")
            .attr("x", bx).attr("y", by)
            .attr("width", 10).attr("height", 7)
            .attr("fill", "#1a1d25").attr("rx", 1);
        }
      }
    });

    // City boundary
    root.append("rect")
      .attr("x", 35).attr("y", 8)
      .attr("width", 840).attr("height", 680).attr("rx", 8)
      .attr("fill", "none").attr("stroke", "#2a2e38")
      .attr("stroke-width", 1.5).attr("stroke-dasharray", "8 4");

    // Data layer groups
    root.append("g").attr("class", "edges");
    root.append("g").attr("class", "trafos");
    root.append("g").attr("class", "nodes");
    root.append("g").attr("class", "labels");
    root.append("g").attr("class", "highlights");

    // Zoom
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.4, 6])
      .on("zoom", (event) => { root.attr("transform", event.transform); });
    svg.call(zoom);
    svg.on("dblclick.zoom", null);
  }, [revision, buses, districts, riverPath]);

  // Live data updates
  useEffect(() => {
    if (!rootGRef.current || !gridState) return;
    const root = d3.select(rootGRef.current);
    const geoMap = busGeoMap.current;
    const genMap = new Map(gridState.generators.map((g) => [g.bus_id, g]));

    // Edges (drawn once per rebuild)
    const edgesG = root.select("g.edges");
    if (edgesG.selectAll("line").empty()) {
      KNOWN_EDGES.forEach(([from, to], idx) => {
        const a = geoMap.get(from);
        const b = geoMap.get(to);
        if (!a || !b) return;
        const tier = Math.min(
          VOLTAGE_TIER(gridState.buses.find((bus) => bus.id === from)?.voltage_kv ?? 33),
          VOLTAGE_TIER(gridState.buses.find((bus) => bus.id === to)?.voltage_kv ?? 33),
        );
        const width = tier === 0 ? 2.5 : tier === 1 ? 1.5 : 0.7;
        edgesG.append("line")
          .attr("class", `edge-${idx}`)
          .attr("x1", a.x).attr("y1", a.y)
          .attr("x2", b.x).attr("y2", b.y)
          .attr("stroke", "#2a2e38").attr("stroke-width", width)
          .attr("stroke-opacity", 0.6);
      });
    }

    // Transformers (drawn once)
    const trafosG = root.select("g.trafos");
    if (trafosG.selectAll("line").empty()) {
      gridState.transformers.forEach((t, idx) => {
        const a = geoMap.get(t.from_bus);
        const b = geoMap.get(t.to_bus);
        if (!a || !b) return;
        trafosG.append("line")
          .attr("class", `tf-line-${idx}`)
          .attr("x1", a.x).attr("y1", a.y).attr("x2", b.x).attr("y2", b.y)
          .attr("stroke", "#3b4050").attr("stroke-width", 1.5).attr("stroke-opacity", 0.5);
        const mx = (a.x + b.x) / 2, my = (a.y + b.y) / 2;
        trafosG.append("circle")
          .attr("class", `tf-dot-${idx}`)
          .attr("cx", mx).attr("cy", my).attr("r", 3).attr("fill", "#3b4050");
      });
    }

    // Bus nodes (drawn once)
    const nodesG = root.select("g.nodes");
    const labelsG = root.select("g.labels");
    if (nodesG.selectAll("g").empty()) {
      for (const bus of gridState.buses) {
        const geo = geoMap.get(bus.id);
        if (!geo) continue;
        const gen = genMap.get(bus.id);
        const isGen = gen != null;
        const tier = VOLTAGE_TIER(bus.voltage_kv);
        const r = isGen
          ? (tier === 0 ? 10 : tier === 1 ? 7 : 5)
          : (tier === 0 ? 7 : tier === 1 ? 4 : 2.5);

        const g = nodesG.append("g").attr("class", `bus-${bus.id}`);
        if (isGen) {
          g.append("circle").attr("class", "outer-ring")
            .attr("cx", geo.x).attr("cy", geo.y).attr("r", r + 3)
            .attr("fill", "none")
            .attr("stroke", GEN_COLOR[gen!.gen_type] ?? "#34d399")
            .attr("stroke-width", 1).attr("stroke-opacity", 0.3);
        }
        g.append("circle").attr("class", "shape")
          .attr("cx", geo.x).attr("cy", geo.y).attr("r", r)
          .attr("fill", "#2a2e38").attr("stroke", "#3b4050").attr("stroke-width", 1);

        g.append("circle")
          .attr("cx", geo.x).attr("cy", geo.y)
          .attr("r", Math.max(r + 8, 12))
          .attr("fill", "transparent").attr("cursor", "pointer")
          .on("mouseenter", (event: MouseEvent) => {
            const rect = containerRef.current!.getBoundingClientRect();
            setTooltip({
              x: event.clientX - rect.left,
              y: event.clientY - rect.top,
              name: geo.district,
              busId: bus.id,
              voltage: `${bus.voltage_kv} kV`,
              genMw: bus.power_generation_mw,
              loadMw: bus.power_load_mw,
              status: bus.status,
              genType: gen?.gen_type,
            });
          })
          .on("mouseleave", hideTooltip);

        if (tier <= 1) {
          const label = isGen ? `${gen!.gen_type.slice(0, 3)} ${bus.id}` : `${bus.id}`;
          labelsG.append("text")
            .attr("class", `lbl-${bus.id}`)
            .attr("x", geo.x).attr("y", geo.y - r - 6)
            .attr("text-anchor", "middle").attr("fill", "#545b6b")
            .attr("font-family", "ui-monospace, monospace")
            .attr("font-size", tier === 0 ? "8px" : "7px")
            .text(label);
        }
      }
    }

    // Per-tick live updates
    for (const bus of gridState.buses) {
      const gen = genMap.get(bus.id);
      const isGen = gen != null;
      const baseColor = isGen
        ? GEN_COLOR[gen!.gen_type] ?? "#34d399"
        : bus.power_load_mw > 5 ? "#fbbf24" : "#3b4050";
      let fill = baseColor;
      let opacity = isGen ? 0.85 : 0.5;
      if (bus.status === "DEGRADED") { fill = "#fbbf24"; opacity = 0.8; }
      if (bus.status === "CRITICAL") { fill = "#f87171"; opacity = 0.9; }
      if (bus.status === "TRIPPED") { fill = "#545b6b"; opacity = 0.25; }
      if (isGen && !gen!.online) { fill = "#545b6b"; opacity = 0.2; }

      const shape = root.select(`g.bus-${bus.id} .shape`);
      shape.attr("fill", fill).attr("fill-opacity", opacity).attr("stroke", fill);
      const outerRing = root.select(`g.bus-${bus.id} .outer-ring`);
      if (!outerRing.empty()) {
        const ringColor = (isGen && !gen!.online) ? "#545b6b" : fill;
        outerRing.attr("stroke", ringColor)
          .attr("stroke-opacity", bus.status === "CRITICAL" ? 0.6 : 0.3);
      }
      if (isGen && gen!.gen_type === "NUCLEAR") {
        shape.attr("filter", gen!.online ? "url(#node-glow)" : null as any);
      }
    }

    // Transformer live updates
    gridState.transformers.forEach((t, idx) => {
      const loading = t.loading_pct / 100;
      const color = t.status === "TRIPPED" ? "#545b6b" : loadingColor(loading);
      const op = t.status === "TRIPPED" ? 0.25 : 0.6;
      root.select(`line.tf-line-${idx}`)
        .attr("stroke", color).attr("stroke-width", 1 + 2 * loading).attr("stroke-opacity", op);
      root.select(`circle.tf-dot-${idx}`)
        .attr("fill", color).attr("fill-opacity", op);
    });

    // Highlight
    const hlG = root.select("g.highlights");
    hlG.selectAll("*").remove();
    if (highlightedAsset) {
      const parts = highlightedAsset.split(".");
      const idNum = parseInt(parts[parts.length - 1]);
      const geo = geoMap.get(idNum);
      if (geo) {
        hlG.append("circle")
          .attr("cx", geo.x).attr("cy", geo.y).attr("r", 20)
          .attr("fill", "none").attr("stroke", "#60a5fa")
          .attr("stroke-width", 2).attr("stroke-dasharray", "5 3").attr("opacity", 0.7);
      }
    }
  }, [gridState, highlightedAsset, hideTooltip]);

  return (
    <div ref={containerRef} className="relative w-full h-full overflow-hidden">
      <svg
        ref={svgRef}
        viewBox="0 0 900 700"
        preserveAspectRatio="xMidYMid meet"
        className="w-full h-full"
        style={{ background: "#0f1117" }}
      />
      {tooltip && (
        <div
          className="absolute bg-[#1a1d25] border border-[#2a2e38] px-3 py-2 shadow-xl z-10 pointer-events-none rounded"
          style={{ left: tooltip.x + 14, top: tooltip.y - 12 }}
        >
          <div className="font-mono text-[11px] text-white/90 font-medium mb-0.5">
            {tooltip.name}
          </div>
          <div className="font-mono text-[10px] text-white/50">
            Bus {tooltip.busId} &middot; {tooltip.voltage}
            {tooltip.genType && <span className="ml-1.5 text-white/40">{tooltip.genType}</span>}
          </div>
          <div className="font-mono text-[10px] text-white/50 mt-0.5">
            Gen: {tooltip.genMw.toFixed(0)} MW &middot; Load: {tooltip.loadMw.toFixed(0)} MW
          </div>
          <div className={`font-mono text-[10px] mt-0.5 ${
            tooltip.status === "CRITICAL" ? "text-red-400" :
            tooltip.status === "DEGRADED" ? "text-yellow-400" :
            "text-green-400"
          }`}>
            {tooltip.status}
          </div>
        </div>
      )}
      <div className="absolute bottom-2 left-2 bg-[#0f1117]/80 backdrop-blur border border-[#2a2e38] px-3 py-2 rounded text-[9px] font-mono text-white/40 flex flex-wrap gap-x-4 gap-y-1">
        {Object.entries(GEN_COLOR).map(([type, color]) => (
          <span key={type} className="flex items-center gap-1">
            <span className="w-2 h-2 rounded-full inline-block" style={{ background: color }} />
            {type}
          </span>
        ))}
        <span className="flex items-center gap-1">
          <span className="w-2 h-2 rounded-full inline-block bg-[#fbbf24]" />
          LOAD
        </span>
      </div>
    </div>
  );
}
