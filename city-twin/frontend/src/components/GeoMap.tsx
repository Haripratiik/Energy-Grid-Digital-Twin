import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { ATLANTA_BUS_LATLNG } from "../data/atlantaGeo";
import { API_BASE } from "../hooks/useGridStream";
import type { GridState, RealGrid } from "../types/grid";

const ATLANTA_CENTER: [number, number] = [33.75, -84.39];

const STATUS_COLOR: Record<string, string> = {
  normal: "#00c97a",
  warning: "#f0a500",
  critical: "#e53e3e",
};

interface TopoLine {
  index: number;
  from_bus: number;
  to_bus: number;
  voltage_kv: number;
}

function lineColor(frac: number): string {
  if (frac > 0.9) return "#e53e3e";
  if (frac > 0.7) return "#f0a500";
  return "#2f7d5b";
}

type Mode = "sim" | "real";

export default function GeoMap({ gridState }: { gridState: GridState | null }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const lineLayerRef = useRef<L.LayerGroup | null>(null);
  const busLayerRef = useRef<L.LayerGroup | null>(null);
  const realLayerRef = useRef<L.LayerGroup | null>(null);
  const realDataRef = useRef<RealGrid | null>(null);
  const topoRef = useRef<TopoLine[]>([]);
  const [mode, setMode] = useState<Mode>("sim");
  const modeRef = useRef<Mode>("sim");
  modeRef.current = mode;

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, {
      center: ATLANTA_CENTER, zoom: 10, zoomControl: true, preferCanvas: true,
    });
    mapRef.current = map;
    map.fitBounds(L.latLngBounds(Object.values(ATLANTA_BUS_LATLNG) as [number, number][]).pad(0.08));

    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      subdomains: "abcd", maxZoom: 19, attribution: "© OpenStreetMap © CARTO",
    }).addTo(map);

    fetch("/atlanta_grid_infra.geojson")
      .then((r) => r.json())
      .then((geo) => {
        if (!mapRef.current) return;
        L.geoJSON(geo, {
          style: () => ({ color: "#2d4a6b", weight: 1, opacity: 0.4 }),
          pointToLayer: (feature, latlng) =>
            feature.properties?.power === "plant"
              ? L.circleMarker(latlng, { radius: 5, color: "#0b0d10", weight: 1, fillColor: "#f0a500", fillOpacity: 0.9 })
              : L.circleMarker(latlng, { radius: 2, stroke: false, fillColor: "#436085", fillOpacity: 0.45 }),
        }).addTo(map);
      })
      .catch(() => undefined);

    lineLayerRef.current = L.layerGroup().addTo(map);
    busLayerRef.current = L.layerGroup().addTo(map);
    realLayerRef.current = L.layerGroup().addTo(map);

    fetch(`${API_BASE}/topology`)
      .then((r) => r.json())
      .then((t) => { topoRef.current = t.lines ?? []; })
      .catch(() => undefined);

    setTimeout(() => map.invalidateSize(), 0);
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(containerRef.current);
    return () => {
      ro.disconnect();
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // Live simulated grid (skipped while showing the real grid).
  useEffect(() => {
    const lineLayer = lineLayerRef.current;
    const busLayer = busLayerRef.current;
    if (!lineLayer || !busLayer || !gridState || modeRef.current === "real") return;

    lineLayer.clearLayers();
    const lines = gridState.lines;
    for (const t of topoRef.current) {
      const a = ATLANTA_BUS_LATLNG[t.from_bus];
      const b = ATLANTA_BUS_LATLNG[t.to_bus];
      const st = lines[t.index];
      if (!a || !b || !st) continue;
      const tripped = st.tripped;
      const loadFrac = Math.min(Math.max(st.flow_pct_of_limit, 0), 1);
      L.polyline([a, b], {
        color: tripped ? "#464c58" : lineColor(st.flow_pct_of_limit),
        weight: (t.voltage_kv >= 300 ? 2.5 : t.voltage_kv >= 100 ? 1.6 : 0.9) + loadFrac * 1.2,
        opacity: tripped ? 0.45 : 0.4 + loadFrac * 0.55,
        dashArray: tripped ? "3 4" : undefined,
      }).addTo(lineLayer);
    }

    busLayer.clearLayers();
    const genBuses = new Set(gridState.generators.map((g) => g.bus_id));
    for (const bus of gridState.buses) {
      const latlng = ATLANTA_BUS_LATLNG[bus.id];
      if (!latlng) continue;
      const isGen = genBuses.has(bus.id);
      const tier = bus.voltage_kv >= 300 ? 3 : bus.voltage_kv >= 100 ? 2 : 1;
      L.circleMarker(latlng, {
        radius: tier === 3 ? 6 : tier === 2 ? 4 : 2.6,
        fillColor: STATUS_COLOR[bus.status] ?? "#8a919e",
        fillOpacity: 0.92, color: isGen ? "#ffffff" : "#0b0d10", weight: isGen ? 1.5 : 0.5,
      }).bindTooltip(`Bus ${bus.id} · ${bus.voltage_kv}kV · ${bus.voltage_magnitude_pu.toFixed(3)}pu`,
        { className: "geo-tip" }).addTo(busLayer);
    }
  }, [gridState]);

  // Mode switch: real grid vs simulated.
  useEffect(() => {
    const map = mapRef.current;
    const real = realLayerRef.current;
    const lineLayer = lineLayerRef.current;
    const busLayer = busLayerRef.current;
    if (!map || !real || !lineLayer || !busLayer) return;

    if (mode === "real") {
      lineLayer.clearLayers();
      busLayer.clearLayers();
      const draw = (grid: RealGrid) => {
        real.clearLayers();
        const byId = new Map(grid.buses.map((b) => [b.id, b]));
        for (const ln of grid.lines) {
          const a = byId.get(ln.from_id);
          const b = byId.get(ln.to_id);
          if (!a || !b) continue;
          const frac = ln.loading_pct / 100;
          L.polyline([[a.lat, a.lon], [b.lat, b.lon]], {
            color: lineColor(frac),
            weight: (ln.voltage_kv >= 500 ? 2.6 : ln.voltage_kv >= 230 ? 1.7 : 1.0) + Math.min(frac, 1) * 1.0,
            opacity: 0.45 + Math.min(frac, 1) * 0.5,
          }).bindTooltip(`${ln.voltage_kv}kV · ${ln.length_km.toFixed(0)}km · ${ln.flow_mw.toFixed(0)}MW (${ln.loading_pct.toFixed(0)}%)`,
            { className: "geo-tip" }).addTo(real);
        }
        for (const b of grid.buses) {
          L.circleMarker([b.lat, b.lon], {
            radius: b.voltage_kv >= 500 ? 5 : b.voltage_kv >= 230 ? 3.5 : 2.2,
            fillColor: b.is_source ? "#7c3aed" : "#5b9bd5",
            fillOpacity: 0.9, color: b.is_source ? "#ffffff" : "#0b0d10", weight: b.is_source ? 1.5 : 0.4,
          }).bindTooltip(`Substation ${b.id} · ${b.voltage_kv}kV${b.is_source ? " · source" : ` · ${b.load_mw.toFixed(0)}MW load`}`,
            { className: "geo-tip" }).addTo(real);
        }
        const pts = grid.buses.map((b) => [b.lat, b.lon] as [number, number]);
        if (pts.length) map.fitBounds(L.latLngBounds(pts).pad(0.05));
      };
      if (realDataRef.current) {
        draw(realDataRef.current);
      } else {
        fetch(`${API_BASE}/real-grid`)
          .then((r) => r.json())
          .then((g: RealGrid) => { realDataRef.current = g; if (modeRef.current === "real") draw(g); })
          .catch(() => undefined);
      }
    } else {
      real.clearLayers();
    }
  }, [mode]);

  const realLegend = mode === "real";

  return (
    <div className="relative h-full w-full bg-bg-primary">
      <div ref={containerRef} className="absolute inset-0" style={{ background: "#0b0d10" }} />

      {/* mode toggle */}
      <div className="absolute top-2 right-2 z-[600] flex border border-border-strong bg-bg-secondary/90 backdrop-blur-sm">
        {(["sim", "real"] as Mode[]).map((m) => (
          <button
            key={m}
            onClick={() => setMode(m)}
            className={`font-mono text-[9px] px-2 py-1 uppercase tracking-wider transition-colors ${
              mode === m ? "bg-accent-blue text-white" : "text-text-muted hover:text-text-secondary"
            }`}
          >
            {m === "sim" ? "Simulated" : "Real Grid"}
          </button>
        ))}
      </div>

      <div className="absolute top-2 left-2 z-[500] bg-bg-secondary/85 border border-border-subtle px-2 py-1 backdrop-blur-sm pointer-events-none max-w-[60%]">
        <span className="font-mono text-[9px] text-text-secondary uppercase tracking-wider">
          {realLegend
            ? "Real Georgia transmission grid · OpenStreetMap topology · DC power flow"
            : "Atlanta metro · simulated grid over real OSM infrastructure"}
        </span>
      </div>

      <div className="absolute bottom-2 left-2 z-[500] bg-bg-secondary/90 border border-border-subtle px-2.5 py-2 backdrop-blur-sm pointer-events-none">
        <div className="font-mono text-[9px] text-text-muted uppercase tracking-wider mb-1">Legend</div>
        {realLegend ? (
          <>
            <LegendRow color="#7c3aed" label="Source / generation substation" />
            <LegendRow color="#5b9bd5" label="Load substation (real)" />
            <LegendRow color="#2f7d5b" label="Line — normal" line />
            <LegendRow color="#f0a500" label="Line — heavy (>70%)" line />
            <LegendRow color="#e53e3e" label="Line — overloaded (>90%)" line />
          </>
        ) : (
          <>
            <LegendRow color="#2d4a6b" label="Real transmission (OSM)" line />
            <LegendRow color="#f0a500" label="Real plant / substation" />
            <div className="my-1 border-t border-border-subtle" />
            <LegendRow color="#2f7d5b" label="Sim line — normal flow" line />
            <LegendRow color="#f0a500" label="Sim line — heavy (>70%)" line />
            <LegendRow color="#e53e3e" label="Sim line — overloaded" line />
            <LegendRow color="#00c97a" label="Sim bus · generator ringed" />
          </>
        )}
      </div>
    </div>
  );
}

function LegendRow({ color, label, line }: { color: string; label: string; line?: boolean }) {
  return (
    <div className="flex items-center gap-1.5 py-0.5">
      <span
        className="inline-block shrink-0"
        style={line ? { width: 12, height: 2, background: color } : { width: 8, height: 8, borderRadius: 9999, background: color }}
      />
      <span className="font-mono text-[9px] text-text-secondary">{label}</span>
    </div>
  );
}
