import { useEffect, useRef, useState, useCallback } from "react";
import * as d3 from "d3";
import type { BusGeo, DistrictRegion, CityMapPreset } from "../data/presets";
import { validatePreset } from "../data/cityMapPresets";
import type { UseCityMapPreset } from "../hooks/useCityMapPreset";

interface Props {
  presetCtx: UseCityMapPreset;
}

export default function CityMapEditor({ presetCtx }: Props) {
  const { preset, allPresets, switchPreset, applyCustom } = presetCtx;

  const [buses, setBuses] = useState<BusGeo[]>(() => structuredClone(preset.buses));
  const [districts, setDistricts] = useState<DistrictRegion[]>(() => structuredClone(preset.districts));
  const [riverPath, setRiverPath] = useState(preset.riverPath);
  const [selected, setSelected] = useState<number | null>(null);
  const [importErr, setImportErr] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  const svgRef = useRef<SVGSVGElement>(null);
  const rootRef = useRef<SVGGElement | null>(null);
  const builtRef = useRef(false);
  const busesRef = useRef(buses);
  busesRef.current = buses;

  // Sync editor state when preset switches externally
  useEffect(() => {
    setBuses(structuredClone(preset.buses));
    setDistricts(structuredClone(preset.districts));
    setRiverPath(preset.riverPath);
    setSelected(null);
    builtRef.current = false;
    if (svgRef.current) {
      d3.select(svgRef.current).selectAll("*").remove();
      rootRef.current = null;
    }
  }, [preset.id]);

  const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v));

  const drawMap = useCallback(() => {
    if (!svgRef.current) return;
    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();
    rootRef.current = null;
    builtRef.current = true;

    const root = svg.append("g").attr("class", "editor-root");
    rootRef.current = root.node();

    // Background
    root.append("rect").attr("width", 900).attr("height", 700).attr("fill", "#0f1117");

    // River
    if (riverPath) {
      root.append("path").attr("d", riverPath)
        .attr("fill", "none").attr("stroke", "#1e3a5f")
        .attr("stroke-width", 18).attr("stroke-linecap", "round").attr("opacity", 0.4);
      root.append("path").attr("d", riverPath)
        .attr("fill", "none").attr("stroke", "#2563eb")
        .attr("stroke-width", 4).attr("stroke-linecap", "round").attr("opacity", 0.2);
    }

    // Districts
    const distG = root.append("g").attr("class", "districts");
    districts.forEach((d) => {
      distG.append("polygon")
        .attr("points", d.points.map((p) => p.join(",")).join(" "))
        .attr("fill", d.color).attr("fill-opacity", 0.07)
        .attr("stroke", d.color).attr("stroke-opacity", 0.25)
        .attr("stroke-width", 1).attr("stroke-dasharray", "4 2");
      const cx = d.points.reduce((s, p) => s + p[0], 0) / d.points.length;
      const cy = d.points.reduce((s, p) => s + p[1], 0) / d.points.length;
      distG.append("text")
        .attr("x", cx).attr("y", cy)
        .attr("text-anchor", "middle").attr("dominant-baseline", "central")
        .attr("fill", d.color).attr("fill-opacity", 0.4)
        .attr("font-family", "ui-sans-serif, system-ui, sans-serif")
        .attr("font-size", "10px").attr("font-weight", "600")
        .text(d.name);
    });

    // Nodes
    const nodesG = root.append("g").attr("class", "nodes");
    const currentBuses = busesRef.current;
    currentBuses.forEach((b) => {
      const g = nodesG.append("g").attr("class", `ebus-${b.id}`).attr("cursor", "grab");
      g.append("circle")
        .attr("cx", b.x).attr("cy", b.y).attr("r", b.id <= 5 ? 10 : b.id <= 25 ? 6 : 3.5)
        .attr("fill", b.id <= 5 ? "#a78bfa" : b.id <= 25 ? "#60a5fa" : "#3b4050")
        .attr("stroke", "#545b6b").attr("stroke-width", 0.5);
      g.append("text")
        .attr("x", b.x).attr("y", b.y - (b.id <= 5 ? 14 : b.id <= 25 ? 10 : 6))
        .attr("text-anchor", "middle").attr("fill", "#545b6b")
        .attr("font-family", "ui-monospace, monospace").attr("font-size", "7px")
        .text(b.id);

      // Invisible larger hit area
      g.append("circle")
        .attr("cx", b.x).attr("cy", b.y).attr("r", 14)
        .attr("fill", "transparent").attr("cursor", "grab");
    });

    // Drag behavior
    const drag = d3.drag<SVGGElement, unknown>()
      .on("start", function () { d3.select(this).attr("cursor", "grabbing"); })
      .on("drag", function (event) {
        const el = d3.select(this);
        const cls = el.attr("class") ?? "";
        const match = cls.match(/ebus-(\d+)/);
        if (!match) return;
        const busId = parseInt(match[1]);
        const nx = clamp(event.x, 10, 890);
        const ny = clamp(event.y, 10, 690);
        el.select("circle:first-child").attr("cx", nx).attr("cy", ny);
        el.selectAll("circle").each(function () {
          d3.select(this).attr("cx", nx).attr("cy", ny);
        });
        el.select("text").attr("x", nx).attr("y", ny - (busId <= 5 ? 14 : busId <= 25 ? 10 : 6));
        setBuses((prev) => prev.map((b) => (b.id === busId ? { ...b, x: Math.round(nx), y: Math.round(ny) } : b)));
      })
      .on("end", function () { d3.select(this).attr("cursor", "grab"); });

    nodesG.selectAll<SVGGElement, unknown>("g").call(drag);

    nodesG.selectAll<SVGGElement, unknown>("g").on("click", function () {
      const cls = d3.select(this).attr("class") ?? "";
      const match = cls.match(/ebus-(\d+)/);
      if (match) setSelected(parseInt(match[1]));
    });

    // Zoom
    const zoom = d3.zoom<SVGSVGElement, unknown>()
      .scaleExtent([0.4, 6])
      .on("zoom", (event) => { root.attr("transform", event.transform); });
    svg.call(zoom);
    svg.on("dblclick.zoom", null);
  }, [districts, riverPath]);

  useEffect(() => { drawMap(); }, [drawMap]);

  const selectedBus = selected != null ? buses.find((b) => b.id === selected) : undefined;

  const handleDistrictChange = (val: string) => {
    if (selected == null) return;
    setBuses((prev) => prev.map((b) => (b.id === selected ? { ...b, district: val } : b)));
  };

  const handleExport = () => {
    const out: CityMapPreset = {
      id: "custom",
      name: "Custom Layout",
      description: "User-created city map layout",
      buses,
      districts,
      riverPath,
    };
    const blob = new Blob([JSON.stringify(out, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "city-map-preset.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleImport = (e: React.ChangeEvent<HTMLInputElement>) => {
    setImportErr(null);
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        const raw = JSON.parse(reader.result as string);
        if (!validatePreset(raw)) {
          setImportErr("Invalid preset: must have exactly 80 buses with unique IDs 1-80, each with id, x, y, district.");
          return;
        }
        setBuses(raw.buses);
        if (Array.isArray(raw.districts)) setDistricts(raw.districts);
        if (typeof raw.riverPath === "string") setRiverPath(raw.riverPath);
        setImportErr(null);
        builtRef.current = false;
      } catch {
        setImportErr("Failed to parse JSON file.");
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  const handleSave = () => {
    const out: CityMapPreset = {
      id: "custom",
      name: "Custom Layout",
      description: "User-created city map layout",
      buses,
      districts,
      riverPath,
    };
    applyCustom(out);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  const handleReset = (id: string) => {
    switchPreset(id);
  };

  return (
    <div className="flex h-full">
      {/* SVG canvas */}
      <div className="flex-1 min-w-0 relative">
        <svg
          ref={svgRef}
          viewBox="0 0 900 700"
          preserveAspectRatio="xMidYMid meet"
          className="w-full h-full"
          style={{ background: "#0f1117" }}
        />
        <div className="absolute top-2 left-2 bg-[#0f1117]/80 backdrop-blur border border-[#2a2e38] px-2 py-1 rounded text-[9px] font-mono text-white/40">
          Drag nodes to reposition · Click to select · Scroll to zoom
        </div>
      </div>

      {/* Sidebar */}
      <div className="w-56 shrink-0 border-l border-border-strong bg-bg-secondary flex flex-col overflow-y-auto">
        <div className="px-3 py-2 border-b border-border-strong">
          <div className="font-mono text-[10px] text-text-muted uppercase tracking-widest mb-2">City Builder</div>

          {/* Selected bus editor */}
          {selectedBus ? (
            <div className="space-y-1.5 mb-3">
              <div className="font-mono text-[10px] text-text-secondary">
                Bus <span className="text-accent-blue">{selectedBus.id}</span>
                <span className="text-text-muted ml-1">
                  ({selectedBus.x}, {selectedBus.y})
                </span>
              </div>
              <label className="block">
                <span className="font-mono text-[9px] text-text-muted uppercase">District</span>
                <input
                  type="text"
                  value={selectedBus.district}
                  onChange={(e) => handleDistrictChange(e.target.value)}
                  className="w-full mt-0.5 bg-bg-primary border border-border-strong text-text-primary text-[10px] font-mono px-2 py-1 rounded focus:outline-none focus:border-accent-blue"
                />
              </label>
            </div>
          ) : (
            <div className="font-mono text-[9px] text-text-muted mb-3">
              Click a node to edit its district label.
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="px-3 py-2 space-y-1.5 border-b border-border-strong">
          <button
            onClick={handleSave}
            className="w-full font-mono text-[9px] uppercase tracking-wide px-2 py-1.5 bg-accent-blue/20 text-accent-blue border border-accent-blue/30 hover:bg-accent-blue/30 transition-colors rounded"
          >
            {saved ? "Saved!" : "Apply to City Map"}
          </button>
          <button
            onClick={handleExport}
            className="w-full font-mono text-[9px] uppercase tracking-wide px-2 py-1.5 bg-bg-tertiary text-text-secondary border border-border-strong hover:bg-bg-secondary transition-colors rounded"
          >
            Export JSON
          </button>
          <label className="block w-full font-mono text-[9px] uppercase tracking-wide px-2 py-1.5 bg-bg-tertiary text-text-secondary border border-border-strong hover:bg-bg-secondary transition-colors rounded text-center cursor-pointer">
            Import JSON
            <input type="file" accept=".json" onChange={handleImport} className="hidden" />
          </label>
          {importErr && (
            <div className="font-mono text-[9px] text-accent-red bg-accent-red/10 border border-accent-red/20 px-2 py-1 rounded">
              {importErr}
            </div>
          )}
        </div>

        {/* Reset to presets */}
        <div className="px-3 py-2 space-y-1">
          <div className="font-mono text-[9px] text-text-muted uppercase tracking-wide mb-1">Reset to preset</div>
          {allPresets
            .filter((p) => p.id !== "custom")
            .map((p) => (
              <button
                key={p.id}
                onClick={() => handleReset(p.id)}
                className="w-full text-left font-mono text-[9px] px-2 py-1 text-text-secondary hover:bg-bg-tertiary transition-colors rounded truncate"
                title={p.description}
              >
                {p.name}
              </button>
            ))}
        </div>

        {/* Bus list */}
        <div className="px-3 py-2 border-t border-border-strong flex-1 min-h-0 overflow-y-auto">
          <div className="font-mono text-[9px] text-text-muted uppercase tracking-wide mb-1">All Buses</div>
          <div className="space-y-px">
            {buses.map((b) => (
              <button
                key={b.id}
                onClick={() => setSelected(b.id)}
                className={`w-full text-left font-mono text-[9px] px-1.5 py-0.5 rounded truncate transition-colors ${
                  selected === b.id
                    ? "bg-accent-blue/20 text-accent-blue"
                    : "text-text-muted hover:text-text-secondary hover:bg-bg-tertiary"
                }`}
              >
                <span className="inline-block w-5 text-right mr-1 tabular-nums">{b.id}</span>
                {b.district}
              </button>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
