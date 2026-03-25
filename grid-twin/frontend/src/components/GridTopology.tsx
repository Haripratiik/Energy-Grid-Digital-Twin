import { useEffect, useRef } from "react";
import * as d3 from "d3";
import type { GridState, LineState } from "../types/grid";
import FaultInjector from "./FaultInjector";

interface Props {
  gridState: GridState | null;
  highlightedAsset: string | null;
}

interface BusPosition {
  id: number;
  x: number;
  y: number;
  type: "gen" | "load" | "junction";
  label: string;
}

const BUS_POSITIONS: BusPosition[] = [
  { id: 1, x: 100, y: 100, type: "gen", label: "Gen 1" },
  { id: 2, x: 480, y: 100, type: "gen", label: "Gen 2" },
  { id: 3, x: 480, y: 420, type: "gen", label: "Gen 3" },
  { id: 4, x: 220, y: 200, type: "junction", label: "4" },
  { id: 5, x: 100, y: 320, type: "load", label: "Load 5" },
  { id: 6, x: 360, y: 420, type: "load", label: "Load 6" },
  { id: 7, x: 360, y: 260, type: "junction", label: "7" },
  { id: 8, x: 480, y: 260, type: "junction", label: "8" },
  { id: 9, x: 220, y: 380, type: "junction", label: "9" },
];

const LINE_DEFS = [
  { from: 1, to: 4 },
  { from: 4, to: 5 },
  { from: 5, to: 6 },
  { from: 3, to: 6 },
  { from: 6, to: 7 },
  { from: 7, to: 8 },
  { from: 8, to: 2 },
  { from: 8, to: 9 },
  { from: 9, to: 4 },
];

const busMap = new Map(BUS_POSITIONS.map((b) => [b.id, b]));

function lineColor(pct: number): string {
  if (pct > 0.8) return "#e53e3e";
  if (pct > 0.6) return "#f0a500";
  return "#00c97a";
}

function lineWidth(pct: number): number {
  return 2 + 4 * pct;
}

function genStatusColor(state: GridState | null, busId: number): string {
  if (!state) return "#00c97a";
  const gen = state.generators.find((g) => g.bus_id === busId);
  if (!gen || !gen.online) return "#464c58";
  const angle = Math.abs(gen.rotor_angle_deg);
  if (angle > 60) return "#e53e3e";
  if (angle > 45) return "#f0a500";
  return "#00c97a";
}

function hexagonPath(cx: number, cy: number, r: number): string {
  const pts: string[] = [];
  for (let i = 0; i < 6; i++) {
    const angle = (Math.PI / 3) * i - Math.PI / 6;
    pts.push(`${cx + r * Math.cos(angle)},${cy + r * Math.sin(angle)}`);
  }
  return `M${pts.join("L")}Z`;
}

export default function GridTopology({ gridState, highlightedAsset }: Props) {
  const svgRef = useRef<SVGSVGElement>(null);
  const initialized = useRef(false);

  useEffect(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);

    if (!initialized.current) {
      initialized.current = true;

      const defs = svg.append("defs");
      const glow = defs
        .append("filter")
        .attr("id", "glow")
        .attr("x", "-50%")
        .attr("y", "-50%")
        .attr("width", "200%")
        .attr("height", "200%");
      glow
        .append("feGaussianBlur")
        .attr("stdDeviation", "3")
        .attr("result", "coloredBlur");
      const merge = glow.append("feMerge");
      merge.append("feMergeNode").attr("in", "coloredBlur");
      merge.append("feMergeNode").attr("in", "SourceGraphic");

      svg.append("g").attr("class", "lines");
      svg.append("g").attr("class", "nodes");
      svg.append("g").attr("class", "labels");

      const linesG = svg.select("g.lines");
      LINE_DEFS.forEach((ld) => {
        const from = busMap.get(ld.from)!;
        const to = busMap.get(ld.to)!;
        linesG
          .append("line")
          .attr("class", `line-${ld.from}-${ld.to}`)
          .attr("x1", from.x)
          .attr("y1", from.y)
          .attr("x2", to.x)
          .attr("y2", to.y)
          .attr("stroke", "#00c97a")
          .attr("stroke-width", 2)
          .attr("stroke-linecap", "round");
      });

      const nodesG = svg.select("g.nodes");
      const labelsG = svg.select("g.labels");
      BUS_POSITIONS.forEach((bus) => {
        if (bus.type === "gen") {
          nodesG
            .append("path")
            .attr("class", `node-${bus.id}`)
            .attr("d", hexagonPath(bus.x, bus.y, 24))
            .attr("fill", "#00c97a")
            .attr("stroke", "#00c97a")
            .attr("stroke-width", 1.5)
            .attr("fill-opacity", 0.15)
            .attr("filter", "url(#glow)");
        } else if (bus.type === "load") {
          nodesG
            .append("circle")
            .attr("class", `node-${bus.id}`)
            .attr("cx", bus.x)
            .attr("cy", bus.y)
            .attr("r", 14)
            .attr("fill", "#1d2128")
            .attr("stroke", "#363b47")
            .attr("stroke-width", 1.5);
        } else {
          nodesG
            .append("circle")
            .attr("class", `node-${bus.id}`)
            .attr("cx", bus.x)
            .attr("cy", bus.y)
            .attr("r", 8)
            .attr("fill", "#1d2128")
            .attr("stroke", "#363b47")
            .attr("stroke-width", 1);
        }

        labelsG
          .append("text")
          .attr("class", `label-${bus.id}`)
          .attr("x", bus.x)
          .attr("y", bus.type === "gen" ? bus.y - 30 : bus.y + (bus.type === "load" ? 26 : 20))
          .attr("text-anchor", "middle")
          .attr("fill", "#8a919e")
          .attr("font-family", "var(--font-mono)")
          .attr("font-size", "10px")
          .text(bus.label);

        if (bus.type === "load") {
          labelsG
            .append("text")
            .attr("class", `mw-${bus.id}`)
            .attr("x", bus.x)
            .attr("y", bus.y + 4)
            .attr("text-anchor", "middle")
            .attr("fill", "#dde1e8")
            .attr("font-family", "var(--font-mono)")
            .attr("font-size", "9px")
            .text("0 MW");
        }

        if (bus.type === "gen") {
          labelsG
            .append("text")
            .attr("class", `mw-${bus.id}`)
            .attr("x", bus.x)
            .attr("y", bus.y + 5)
            .attr("text-anchor", "middle")
            .attr("fill", "#dde1e8")
            .attr("font-family", "var(--font-mono)")
            .attr("font-size", "10px")
            .text("0 MW");
        }
      });
    }

    if (!gridState) return;
    const svg2 = d3.select(svgRef.current);

    const lineMap = new Map<string, LineState>(
      gridState.lines.map((l) => [l.id, l])
    );

    LINE_DEFS.forEach((ld) => {
      const lineId = `${ld.from}-${ld.to}`;
      const ls = lineMap.get(lineId);
      const line = svg2.select(`line.line-${ld.from}-${ld.to}`);
      if (!ls) return;

      if (ls.tripped) {
        line
          .attr("stroke", "#464c58")
          .attr("stroke-width", 2)
          .attr("stroke-dasharray", "4 2")
          .attr("opacity", 0.3);
      } else {
        const pct = ls.flow_pct_of_limit;
        line
          .attr("stroke", lineColor(pct))
          .attr("stroke-width", lineWidth(pct))
          .attr("stroke-dasharray", pct > 0.1 ? "8 4" : "none")
          .attr("opacity", 1);
      }
    });

    BUS_POSITIONS.forEach((bus) => {
      if (bus.type === "gen") {
        const color = genStatusColor(gridState, bus.id);
        const node = svg2.select(`path.node-${bus.id}`);
        node.attr("fill", color).attr("fill-opacity", 0.15).attr("stroke", color);
        if (color === "#e53e3e") {
          node.classed("pulse-red", true);
        } else {
          node.classed("pulse-red", false);
        }
        const gen = gridState.generators.find((g) => g.bus_id === bus.id);
        svg2
          .select(`text.mw-${bus.id}`)
          .text(gen ? `${gen.electrical_power_mw.toFixed(0)} MW` : "OFF");
      }
      if (bus.type === "load") {
        const bs = gridState.buses.find((b) => b.id === bus.id);
        svg2
          .select(`text.mw-${bus.id}`)
          .text(bs ? `${bs.power_load_mw.toFixed(0)} MW` : "");
      }
    });
  }, [gridState, highlightedAsset]);

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-border-subtle bg-bg-tertiary">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          Grid Topology · IEEE 9-Bus
        </span>
      </div>
      <div className="flex-1 flex items-center justify-center bg-bg-primary p-2">
        <svg
          ref={svgRef}
          viewBox="0 0 600 500"
          className="w-full h-full max-w-[600px] max-h-[500px]"
          style={{ background: "transparent" }}
        />
      </div>
      <FaultInjector />
    </div>
  );
}
