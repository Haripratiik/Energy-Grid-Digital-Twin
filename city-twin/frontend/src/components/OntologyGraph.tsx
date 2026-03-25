import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import type {
  GridAsset,
  OntologyResponse,
  PropagationResponse,
  GridState,
} from "../types/grid";

interface Props {
  ontology: OntologyResponse | null;
  gridState: GridState | null;
  fetchPropagation: (alertId: string) => Promise<PropagationResponse | null>;
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
    case "GridSystem":
      return 22;
    case "Region":
      return 18;
    case "Substation":
      return 10;
    case "Generator":
      return 10;
    case "TransmissionLine":
      return 5;
    case "Transformer":
      return 6;
    case "LoadBus":
      return 5;
    default:
      return 6;
  }
}

export default function OntologyGraph({
  ontology,
  gridState,
  fetchPropagation,
}: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const simRef = useRef<d3.Simulation<any, any> | null>(null);
  const [tooltip, setTooltip] = useState<{
    x: number;
    y: number;
    asset: GridAsset;
  } | null>(null);

  /* keep gridState & fetchPropagation available for future tooltip actions */
  const gridRef = useRef(gridState);
  gridRef.current = gridState;
  const propRef = useRef(fetchPropagation);
  propRef.current = fetchPropagation;

  useEffect(() => {
    if (!svgRef.current || !ontology) return;

    const svg = d3.select(svgRef.current);
    const width = svgRef.current.clientWidth || 400;
    const height = svgRef.current.clientHeight || 500;

    svg.selectAll("*").remove();

    const g = svg.append("g");

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.2, 4])
      .on("zoom", (event) => g.attr("transform", event.transform));
    svg.call(zoom);

    const nodes = ontology.nodes.map((n) => ({ ...n, id: n.rid }));
    const links = ontology.edges.map((e) => ({
      source: e.source_rid,
      target: e.target_rid,
      link_type: e.link_type,
    }));

    const simulation = d3
      .forceSimulation(nodes as any)
      .force(
        "link",
        d3
          .forceLink(links)
          .id((d: any) => d.id)
          .distance(55),
      )
      .force("charge", d3.forceManyBody().strength(-100))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force(
        "collide",
        d3.forceCollide().radius((d: any) => nodeR(d.object_type) + 5),
      );

    simRef.current = simulation;

    /* edges */
    const link = g
      .append("g")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", "#252830")
      .attr("stroke-width", 1)
      .attr("stroke-opacity", 0.6);

    /* nodes */
    const node = g
      .append("g")
      .selectAll<SVGGElement, any>("g")
      .data(nodes)
      .join("g")
      .call(
        d3
          .drag<SVGGElement, any>()
          .on("start", (event, d: any) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (event, d: any) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", (event, d: any) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          }) as any,
      );

    node.each(function (d: any) {
      const el = d3.select(this);
      const r = nodeR(d.object_type);
      const statusFill = STATUS_FILL[d.status];
      const baseFill = TYPE_FILL[d.object_type] ?? "#8a919e";
      const op = d.status === "TRIPPED" ? 0.3 : 0.7;

      let fill = statusFill || baseFill;

      if (d.object_type === "Generator") {
        const genType = d.properties?.gen_type as string | undefined;
        if (genType && GEN_TYPE_COLOR[genType]) fill = GEN_TYPE_COLOR[genType];
        if (statusFill) fill = statusFill;
      }

      const objType: string = d.object_type;

      switch (objType) {
        case "GridSystem":
          el.append("circle")
            .attr("r", r)
            .attr("fill", fill)
            .attr("fill-opacity", op)
            .attr("stroke", fill)
            .attr("stroke-width", 1.5);
          break;

        case "Region":
          el.append("rect")
            .attr("x", -r)
            .attr("y", -r * 0.6)
            .attr("width", r * 2)
            .attr("height", r * 1.2)
            .attr("rx", 5)
            .attr("fill", fill)
            .attr("fill-opacity", op)
            .attr("stroke", fill)
            .attr("stroke-width", 1);
          break;

        case "Substation":
          el.append("rect")
            .attr("x", -r)
            .attr("y", -r)
            .attr("width", r * 2)
            .attr("height", r * 2)
            .attr("rx", 3)
            .attr("fill", "#1d2128")
            .attr("fill-opacity", op)
            .attr("stroke", fill)
            .attr("stroke-width", 1.5);
          break;

        case "Generator":
        case "Transformer":
          el.append("rect")
            .attr("x", -r)
            .attr("y", -r)
            .attr("width", r * 2)
            .attr("height", r * 2)
            .attr("transform", "rotate(45)")
            .attr("fill", fill)
            .attr("fill-opacity", op)
            .attr("stroke", fill)
            .attr("stroke-width", 1);
          break;

        default:
          el.append("circle")
            .attr("r", r)
            .attr("fill", fill)
            .attr("fill-opacity", op)
            .attr("stroke", fill)
            .attr("stroke-width", 0.5);
      }
    });

    node
      .append("text")
      .attr("dy", (d: any) => nodeR(d.object_type) + 12)
      .attr("text-anchor", "middle")
      .attr("fill", "#8a919e")
      .attr("font-family", "var(--font-mono)")
      .attr("font-size", "8px")
      .text((d: any) => d.display_name);

    node.on("click", (event, d: any) => {
      event.stopPropagation();
      const rect = svgRef.current!.getBoundingClientRect();
      setTooltip({
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
        asset: d,
      });
    });

    svg.on("click", (event) => {
      if (event.target === svgRef.current) setTooltip(null);
    });

    simulation.on("tick", () => {
      link
        .attr("x1", (d: any) => d.source.x)
        .attr("y1", (d: any) => d.source.y)
        .attr("x2", (d: any) => d.target.x)
        .attr("y2", (d: any) => d.target.y);
      node.attr("transform", (d: any) => `translate(${d.x},${d.y})`);
    });

    return () => {
      simulation.stop();
    };
  }, [ontology]);

  const nc = ontology?.nodes.length ?? 0;
  const ec = ontology?.edges.length ?? 0;
  const tc = ontology
    ? new Set(ontology.nodes.map((n) => n.object_type)).size
    : 0;

  return (
    <div className="flex flex-col h-full relative">
      <div className="px-3 py-1.5 border-b border-border-strong bg-bg-tertiary">
        <div className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          <span className="text-accent-blue">02</span> Ontology · Propagation
        </div>
        <div className="font-mono text-[9px] text-text-muted">
          {nc} objects · {ec} links · {tc} types
        </div>
      </div>

      <div className="flex-1 relative">
        <svg ref={svgRef} className="w-full h-full" />

        {tooltip && (
          <div
            className="absolute bg-bg-elevated border border-border-strong p-2 rounded shadow-lg max-w-[240px] z-10"
            style={{ left: tooltip.x + 10, top: tooltip.y + 10 }}
          >
            <div className="font-mono text-[10px] text-text-code mb-1">
              {tooltip.asset.display_name}
            </div>
            <div className="font-mono text-[9px] text-text-muted mb-1 break-all">
              {tooltip.asset.rid}
            </div>
            <div className="font-mono text-[9px] text-text-secondary">
              Type:{" "}
              <span className="text-text-primary">
                {tooltip.asset.object_type}
              </span>
            </div>
            <div className="font-mono text-[9px] text-text-secondary">
              Status:{" "}
              <span
                className={
                  tooltip.asset.status === "CRITICAL" ||
                  tooltip.asset.status === "OVERLOADED"
                    ? "text-accent-red"
                    : tooltip.asset.status === "DEGRADED"
                      ? "text-accent-yellow"
                      : "text-accent-green"
                }
              >
                {tooltip.asset.status}
              </span>
            </div>
            <pre className="font-mono text-[8px] text-text-secondary mt-1 whitespace-pre-wrap break-all max-h-24 overflow-y-auto">
              {JSON.stringify(tooltip.asset.properties, null, 1)}
            </pre>
            <button
              onClick={() => setTooltip(null)}
              className="font-mono text-[8px] text-text-muted mt-1 hover:text-text-primary"
            >
              [close]
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
