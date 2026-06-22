import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import { API_BASE } from "../hooks/useGridStream";
import type { GridAsset, OntologyResponse } from "../types/grid";

interface Props {
  ontology: OntologyResponse | null;
  /** Which grid to show — shared with the Topology panel (driven from App). */
  source: "synthetic" | "real" | "custom";
  /** Asset rid to ring (clicked in the alert feed / decision queue). */
  highlightedAsset: string | null;
}

const GEN_TYPE_COLOR: Record<string, string> = {
  NUCLEAR: "#7c3aed",
  HYDRO: "#1a6cf5",
  WIND: "#00c97a",
  SOLAR: "#f0a500",
  GAS: "#e53e3e",
  THERMAL: "#f97316",
};

const TYPE_FILL: Record<string, string> = {
  GridSystem: "#1040a0",
  Region: "#1a6cf5",
  Substation: "#363b47",
  Generator: "#00c97a",
  TransmissionLine: "#8a919e",
  Transformer: "#f0a500",
  LoadBus: "#f0a500",
};

const STATUS_FILL: Record<string, string> = {
  DEGRADED: "#f0a500",
  OVERLOADED: "#e53e3e",
  CRITICAL: "#e53e3e",
  TRIPPED: "#464c58",
};

function nodeR(type: string): number {
  switch (type) {
    case "GridSystem": return 22;
    case "Region": return 18;
    case "Substation": return 10;
    case "Generator": return 10;
    case "TransmissionLine": return 5;
    case "Transformer": return 6;
    case "LoadBus": return 5;
    default: return 6;
  }
}

/** Status-aware colour for a node's shape. */
function colorFor(objType: string, status: string, genType?: string): string {
  const statusFill = STATUS_FILL[status];
  if (objType === "Generator") {
    if (statusFill) return statusFill;
    if (genType && GEN_TYPE_COLOR[genType]) return GEN_TYPE_COLOR[genType];
    return TYPE_FILL.Generator;
  }
  return statusFill || TYPE_FILL[objType] || "#8a919e";
}

/** Update fill/stroke/opacity of an already-built node selection in place. */
function applyStatus(node: d3.Selection<SVGGElement, any, any, any>) {
  node.each(function (d: any) {
    const color = colorFor(d.object_type, d.status, d.properties?.gen_type);
    const op = d.status === "TRIPPED" ? 0.3 : 0.7;
    const shape = d3.select(this).select(".node-shape");
    if (d.object_type === "Substation") {
      shape.attr("fill", "#1d2128").attr("fill-opacity", op).attr("stroke", color);
    } else {
      shape.attr("fill", color).attr("fill-opacity", op).attr("stroke", color);
    }
  });
}

export default function OntologyGraph({ ontology, source, highlightedAsset }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const simRef = useRef<d3.Simulation<any, any> | null>(null);
  const nodeSelRef = useRef<d3.Selection<SVGGElement, any, any, any> | null>(null);
  const builtSourceRef = useRef<string | null>(null);
  const [tooltip, setTooltip] = useState<{ x: number; y: number; asset: GridAsset } | null>(null);
  const [realOnt, setRealOnt] = useState<OntologyResponse | null>(null);
  const [customOnt, setCustomOnt] = useState<OntologyResponse | null>(null);

  // Lazily fetch the real-Georgia ontology the first time it's selected.
  useEffect(() => {
    if (source !== "real" || realOnt) return;
    fetch(`${API_BASE}/real-grid/ontology`).then((r) => r.json()).then(setRealOnt).catch(() => {});
  }, [source, realOnt]);

  // The custom ontology changes whenever the user re-simulates, so re-fetch on
  // every entry and force a rebuild with the fresh structure.
  useEffect(() => {
    if (source !== "custom") return;
    fetch(`${API_BASE}/custom-grid/ontology`)
      .then((r) => r.json())
      .then((d) => { builtSourceRef.current = null; setCustomOnt(d); })
      .catch(() => {});
  }, [source]);

  const active = source === "real" ? realOnt : source === "custom" ? customOnt : ontology;

  // --- (re)build the graph whenever the active source changes ---
  useEffect(() => {
    if (!svgRef.current || !active) return;
    if (builtSourceRef.current === source) return; // built already; status effect updates it
    builtSourceRef.current = source;

    const big = active.nodes.length > 120;
    const rscale = big ? 0.6 : 1;
    const showLabel = (d: any) =>
      !big || d.object_type === "GridSystem" || d.object_type === "Generator" || d.object_type === "Region";

    const svg = d3.select(svgRef.current);
    const width = svgRef.current.clientWidth || 400;
    const height = svgRef.current.clientHeight || 500;
    svg.selectAll("*").remove();

    const g = svg.append("g");
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.12, 4])
      .on("zoom", (event) => g.attr("transform", event.transform));
    svg.call(zoom);

    const nodes = active.nodes.map((n) => ({ ...n, id: n.rid }));
    const links = active.edges.map((e) => ({
      source: e.source_rid, target: e.target_rid, link_type: e.link_type,
    }));

    simRef.current?.stop();
    const simulation = d3.forceSimulation(nodes as any)
      .force("link", d3.forceLink(links).id((d: any) => d.id).distance(big ? 28 : 55))
      .force("charge", d3.forceManyBody().strength(big ? -45 : -100))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide().radius((d: any) => nodeR(d.object_type) * rscale + (big ? 2 : 5)));
    simRef.current = simulation;

    const link = g.append("g").selectAll("line").data(links).join("line")
      .attr("stroke", "#252830").attr("stroke-width", 1).attr("stroke-opacity", 0.6);

    const node = g.append("g").selectAll<SVGGElement, any>("g").data(nodes).join("g")
      .call(d3.drag<SVGGElement, any>()
        .on("start", (event, d: any) => { if (!event.active) simulation.alphaTarget(0.3).restart(); d.fx = d.x; d.fy = d.y; })
        .on("drag", (event, d: any) => { d.fx = event.x; d.fy = event.y; })
        .on("end", (event, d: any) => { if (!event.active) simulation.alphaTarget(0); d.fx = null; d.fy = null; }) as any);
    nodeSelRef.current = node;

    node.each(function (d: any) {
      const el = d3.select(this);
      const r = nodeR(d.object_type) * rscale;
      switch (d.object_type as string) {
        case "GridSystem":
          el.append("circle").attr("class", "node-shape").attr("r", r).attr("stroke-width", 1.5);
          break;
        case "Region":
          el.append("rect").attr("class", "node-shape").attr("x", -r).attr("y", -r * 0.6)
            .attr("width", r * 2).attr("height", r * 1.2).attr("rx", 5).attr("stroke-width", 1);
          break;
        case "Substation":
          el.append("rect").attr("class", "node-shape").attr("x", -r).attr("y", -r)
            .attr("width", r * 2).attr("height", r * 2).attr("rx", 3).attr("stroke-width", 1.5);
          break;
        case "Generator":
        case "Transformer":
          el.append("rect").attr("class", "node-shape").attr("x", -r).attr("y", -r)
            .attr("width", r * 2).attr("height", r * 2).attr("transform", "rotate(45)").attr("stroke-width", 1);
          break;
        default:
          el.append("circle").attr("class", "node-shape").attr("r", r).attr("stroke-width", 0.5);
      }
    });
    applyStatus(node);

    node.append("text")
      .attr("dy", (d: any) => nodeR(d.object_type) * rscale + 12)
      .attr("text-anchor", "middle").attr("fill", "#8a919e")
      .attr("font-family", "var(--font-mono)").attr("font-size", "8px")
      .text((d: any) => (showLabel(d) ? d.display_name : ""));

    node.on("click", (event, d: any) => {
      event.stopPropagation();
      const rect = svgRef.current!.getBoundingClientRect();
      setTooltip({ x: event.clientX - rect.left, y: event.clientY - rect.top, asset: d });
    });
    svg.on("click", (event) => { if (event.target === svgRef.current) setTooltip(null); });

    simulation.on("tick", () => {
      link.attr("x1", (d: any) => d.source.x).attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x).attr("y2", (d: any) => d.target.y);
      node.attr("transform", (d: any) => `translate(${d.x},${d.y})`);
    });
  }, [active, source]);

  // --- live status update in place (no re-layout) on every poll ---
  useEffect(() => {
    const node = nodeSelRef.current;
    if (!node || !active || builtSourceRef.current !== source) return;
    const statusByRid = new Map(active.nodes.map((n) => [n.rid, n.status]));
    node.each((d: any) => { d.status = statusByRid.get(d.id) ?? d.status; });
    applyStatus(node);
  }, [active, source]);

  // Ring the asset clicked in the alert feed / decision queue. The ring is a
  // child of the node <g>, so it tracks the node as the force layout settles.
  useEffect(() => {
    const node = nodeSelRef.current;
    if (!node || builtSourceRef.current !== source) return;
    node.selectAll(".hl-ring").remove();
    if (!highlightedAsset) return;
    const rscale = (active?.nodes.length ?? 0) > 120 ? 0.6 : 1;
    node.filter((d: any) => d.id === highlightedAsset).each(function (d: any) {
      d3.select(this).append("circle")
        .attr("class", "hl-ring")
        .attr("r", nodeR(d.object_type) * rscale + 7)
        .attr("fill", "none").attr("stroke", "#5bbcff")
        .attr("stroke-width", 2).attr("opacity", 0.95);
    });
  }, [highlightedAsset, active, source]);

  useEffect(() => () => { simRef.current?.stop(); }, []);

  const nc = active?.nodes.length ?? 0;
  const ec = active?.edges.length ?? 0;
  const abnormal = active ? active.nodes.filter((n) => n.status !== "NOMINAL").length : 0;

  return (
    <div className="flex flex-col h-full relative">
      <div className="px-3 py-1.5 border-b border-border-strong bg-bg-tertiary flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
            <span className="text-accent-blue">02</span> Ontology ·{" "}
            {source === "real" ? "Real Georgia (OSM)" : source === "custom" ? "Custom Grid" : "Live Synthetic"}
          </div>
          <div className="font-mono text-[9px] text-text-muted truncate">
            {nc} objects · {ec} links ·{" "}
            <span className={abnormal > 0 ? "text-accent-yellow" : "text-accent-green"}>
              {abnormal} non-nominal
            </span>
            {source === "real" && <span className="text-text-muted"> · real topology, est. params</span>}
            {source === "custom" && <span className="text-text-muted"> · user-built</span>}
          </div>
        </div>
        <span
          className="font-mono text-[8px] text-text-muted uppercase tracking-wide shrink-0 pt-0.5"
          title="The ontology follows the grid you pick in the Topology panel above"
        >
          follows ① Topology
        </span>
      </div>
      {source === "real" && !realOnt && (
        <div className="px-3 py-1 font-mono text-[9px] text-accent-yellow animate-pulse shrink-0">
          loading real Georgia ontology…
        </div>
      )}
      {source === "custom" && (!customOnt || customOnt.nodes.length === 0) && (
        <div className="px-3 py-1 font-mono text-[9px] text-text-muted shrink-0">
          No custom grid yet — build &amp; simulate one in the Custom topology view.
        </div>
      )}

      <div className="flex-1 relative">
        <svg ref={svgRef} className="w-full h-full" />
        {tooltip && (
          <div
            className="absolute bg-bg-elevated border border-border-strong p-2 rounded shadow-lg max-w-[240px] z-10"
            style={{ left: tooltip.x + 10, top: tooltip.y + 10 }}
          >
            <div className="font-mono text-[10px] text-text-code mb-1">{tooltip.asset.display_name}</div>
            <div className="font-mono text-[9px] text-text-muted mb-1 break-all">{tooltip.asset.rid}</div>
            <div className="font-mono text-[9px] text-text-secondary">
              Type: <span className="text-text-primary">{tooltip.asset.object_type}</span>
            </div>
            <div className="font-mono text-[9px] text-text-secondary">
              Status:{" "}
              <span className={
                tooltip.asset.status === "CRITICAL" || tooltip.asset.status === "OVERLOADED"
                  ? "text-accent-red"
                  : tooltip.asset.status === "DEGRADED" || tooltip.asset.status === "TRIPPED"
                    ? "text-accent-yellow" : "text-accent-green"
              }>
                {tooltip.asset.status}
              </span>
            </div>
            <pre className="font-mono text-[8px] text-text-secondary mt-1 whitespace-pre-wrap break-all max-h-24 overflow-y-auto">
              {JSON.stringify(tooltip.asset.properties, null, 1)}
            </pre>
            <button onClick={() => setTooltip(null)} className="font-mono text-[8px] text-text-muted mt-1 hover:text-text-primary">
              [close]
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
