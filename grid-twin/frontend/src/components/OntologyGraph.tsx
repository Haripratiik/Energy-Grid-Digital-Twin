import { useEffect, useRef, useState } from "react";
import * as d3 from "d3";
import type {
  GridAsset,
  GridState,
  OntologyResponse,
  PropagationResponse,
} from "../types/grid";

interface Props {
  ontology: OntologyResponse | null;
  gridState: GridState | null;
  fetchPropagation: (alertId: string) => Promise<PropagationResponse | null>;
}

const TYPE_COLORS: Record<string, string> = {
  GridSystem: "#1040a0",
  Substation: "#1a6cf5",
  Generator: "#00c97a",
  TransmissionLine: "#8a919e",
  LoadBus: "#f0a500",
};

const STATUS_COLORS: Record<string, string> = {
  NOMINAL: "",
  DEGRADED: "#f0a500",
  OVERLOADED: "#e53e3e",
  CRITICAL: "#e53e3e",
  TRIPPED: "#464c58",
};

function nodeRadius(type: string): number {
  switch (type) {
    case "GridSystem":
      return 20;
    case "Substation":
      return 11;
    case "Generator":
      return 9;
    case "TransmissionLine":
      return 7;
    case "LoadBus":
      return 7;
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

  useEffect(() => {
    if (!svgRef.current || !ontology) return;

    const svg = d3.select(svgRef.current);
    const width = svgRef.current.clientWidth || 400;
    const height = svgRef.current.clientHeight || 500;

    svg.selectAll("*").remove();

    const g = svg.append("g");

    const zoom = d3
      .zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.3, 3])
      .on("zoom", (event) => {
        g.attr("transform", event.transform);
      });
    svg.call(zoom);

    const nodes = ontology.nodes.map((n) => ({
      ...n,
      id: n.rid,
    }));
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
          .distance(60)
      )
      .force("charge", d3.forceManyBody().strength(-120))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collide", d3.forceCollide().radius(25));

    simRef.current = simulation;

    const link = g
      .append("g")
      .selectAll("line")
      .data(links)
      .join("line")
      .attr("stroke", "#252830")
      .attr("stroke-width", 1)
      .attr("stroke-opacity", 0.6);

    const node = g
      .append("g")
      .selectAll("g")
      .data(nodes)
      .join("g")
      .call(
        d3.drag<SVGGElement, any>()
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
          }) as any
      );

    node.each(function (d: any) {
      const el = d3.select(this);
      const r = nodeRadius(d.object_type);
      const baseColor = STATUS_COLORS[d.status] || TYPE_COLORS[d.object_type] || "#8a919e";
      const fillColor = baseColor || TYPE_COLORS[d.object_type] || "#8a919e";

      if (d.object_type === "Substation") {
        el.append("rect")
          .attr("x", -r)
          .attr("y", -r)
          .attr("width", r * 2)
          .attr("height", r * 2)
          .attr("rx", 4)
          .attr("fill", fillColor)
          .attr("fill-opacity", d.status === "TRIPPED" ? 0.3 : 0.7)
          .attr("stroke", fillColor)
          .attr("stroke-width", 1);
      } else if (d.object_type === "Generator") {
        el.append("rect")
          .attr("x", -r)
          .attr("y", -r)
          .attr("width", r * 2)
          .attr("height", r * 2)
          .attr("transform", `rotate(45)`)
          .attr("fill", fillColor)
          .attr("fill-opacity", d.status === "TRIPPED" ? 0.3 : 0.7)
          .attr("stroke", fillColor)
          .attr("stroke-width", 1);
      } else {
        el.append("circle")
          .attr("r", r)
          .attr("fill", fillColor)
          .attr("fill-opacity", d.status === "TRIPPED" ? 0.3 : 0.7)
          .attr("stroke", fillColor)
          .attr("stroke-width", 1);
      }
    });

    node
      .append("text")
      .attr("dy", (d: any) => nodeRadius(d.object_type) + 12)
      .attr("text-anchor", "middle")
      .attr("fill", "#8a919e")
      .attr("font-family", "var(--font-mono)")
      .attr("font-size", "9px")
      .text((d: any) => d.display_name);

    node.on("click", (event, d: any) => {
      const rect = svgRef.current!.getBoundingClientRect();
      setTooltip({
        x: event.clientX - rect.left,
        y: event.clientY - rect.top,
        asset: d,
      });
    });

    svg.on("click", (event) => {
      if (event.target === svgRef.current) {
        setTooltip(null);
      }
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

  const nodeCount = ontology?.nodes.length ?? 0;
  const edgeCount = ontology?.edges.length ?? 0;
  const typeCount = ontology
    ? new Set(ontology.nodes.map((n) => n.object_type)).size
    : 0;

  return (
    <div className="flex flex-col h-full relative">
      <div className="px-3 py-2 border-b border-border-subtle bg-bg-tertiary">
        <div className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          Foundry Ontology
        </div>
        <div className="font-mono text-[9px] text-text-muted">
          {nodeCount} objects · {edgeCount} links · {typeCount} types
        </div>
      </div>
      <div className="flex-1 relative">
        <svg ref={svgRef} className="w-full h-full" />
        {tooltip && (
          <div
            className="absolute bg-bg-elevated border border-border-strong p-2 rounded shadow-lg max-w-[220px] z-10"
            style={{ left: tooltip.x + 10, top: tooltip.y + 10 }}
          >
            <div className="font-mono text-[10px] text-text-code mb-1">
              {tooltip.asset.display_name}
            </div>
            <div className="font-mono text-[9px] text-text-muted mb-1">
              {tooltip.asset.rid}
            </div>
            <div className="font-mono text-[9px] text-text-secondary">
              Status:{" "}
              <span
                className={
                  tooltip.asset.status === "CRITICAL"
                    ? "text-accent-red"
                    : tooltip.asset.status === "OVERLOADED"
                      ? "text-accent-red"
                      : tooltip.asset.status === "DEGRADED"
                        ? "text-accent-yellow"
                        : "text-accent-green"
                }
              >
                {tooltip.asset.status}
              </span>
            </div>
            <pre className="font-mono text-[8px] text-text-secondary mt-1 whitespace-pre-wrap break-all">
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
