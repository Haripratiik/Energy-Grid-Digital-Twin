import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { BUS_GEO_MAP } from "../data/cityGeo";
import { API_BASE } from "../hooks/useGridStream";
import type { GridState } from "../types/grid";

// Atlanta metro bbox the real infrastructure was fetched for (S, W, N, E).
const BBOX = { s: 33.55, w: -84.66, n: 34.06, e: -84.05 };
const SVG_W = 900;
const SVG_H = 700;

function toLatLng(x: number, y: number): [number, number] {
  const lng = BBOX.w + (x / SVG_W) * (BBOX.e - BBOX.w);
  const lat = BBOX.n - (y / SVG_H) * (BBOX.n - BBOX.s);
  return [lat, lng];
}

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

export default function GeoMap({ gridState }: { gridState: GridState | null }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const lineLayerRef = useRef<L.LayerGroup | null>(null);
  const busLayerRef = useRef<L.LayerGroup | null>(null);
  const topoRef = useRef<TopoLine[]>([]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, {
      center: [(BBOX.s + BBOX.n) / 2, (BBOX.w + BBOX.e) / 2],
      zoom: 10,
      zoomControl: true,
      preferCanvas: true,
    });
    mapRef.current = map;

    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      subdomains: "abcd",
      maxZoom: 19,
      attribution: "© OpenStreetMap © CARTO",
    }).addTo(map);

    // Real transmission infrastructure (OpenStreetMap GeoJSON), drawn underneath.
    fetch("/atlanta_grid_infra.geojson")
      .then((r) => r.json())
      .then((geo) => {
        if (!mapRef.current) return;
        L.geoJSON(geo, {
          style: () => ({ color: "#2d4a6b", weight: 1, opacity: 0.5 }),
          pointToLayer: (feature, latlng) =>
            feature.properties?.power === "plant"
              ? L.circleMarker(latlng, { radius: 5, color: "#0b0d10", weight: 1, fillColor: "#f0a500", fillOpacity: 0.9 })
              : L.circleMarker(latlng, { radius: 2, stroke: false, fillColor: "#436085", fillOpacity: 0.5 }),
        }).addTo(map);
      })
      .catch(() => undefined);

    // Simulated network: lines under buses.
    lineLayerRef.current = L.layerGroup().addTo(map);
    busLayerRef.current = L.layerGroup().addTo(map);

    // Static connectivity for the simulated grid.
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
      lineLayerRef.current = null;
      busLayerRef.current = null;
    };
  }, []);

  // Redraw the live simulated grid (lines + buses) on every state update.
  useEffect(() => {
    const lineLayer = lineLayerRef.current;
    const busLayer = busLayerRef.current;
    if (!lineLayer || !busLayer || !gridState) return;

    // --- transmission lines, coloured by live loading ---
    lineLayer.clearLayers();
    const lines = gridState.lines;
    for (const t of topoRef.current) {
      const a = BUS_GEO_MAP.get(t.from_bus);
      const b = BUS_GEO_MAP.get(t.to_bus);
      const st = lines[t.index];
      if (!a || !b || !st) continue;
      const tripped = st.tripped;
      const loadFrac = Math.min(Math.max(st.flow_pct_of_limit, 0), 1);
      L.polyline([toLatLng(a.x, a.y), toLatLng(b.x, b.y)], {
        color: tripped ? "#464c58" : lineColor(st.flow_pct_of_limit),
        // opacity tracks live loading so flows visibly vary even when "green"
        weight: (t.voltage_kv >= 300 ? 2.5 : t.voltage_kv >= 100 ? 1.6 : 0.9) + loadFrac * 1.2,
        opacity: tripped ? 0.45 : 0.4 + loadFrac * 0.55,
        dashArray: tripped ? "3 4" : undefined,
      }).addTo(lineLayer);
    }

    // --- buses, coloured by live status ---
    busLayer.clearLayers();
    const genBuses = new Set(gridState.generators.map((g) => g.bus_id));
    for (const bus of gridState.buses) {
      const geo = BUS_GEO_MAP.get(bus.id);
      if (!geo) continue;
      const isGen = genBuses.has(bus.id);
      const tier = bus.voltage_kv >= 300 ? 3 : bus.voltage_kv >= 100 ? 2 : 1;
      L.circleMarker(toLatLng(geo.x, geo.y), {
        radius: tier === 3 ? 6 : tier === 2 ? 4 : 2.6,
        fillColor: STATUS_COLOR[bus.status] ?? "#8a919e",
        fillOpacity: 0.92,
        color: isGen ? "#ffffff" : "#0b0d10",
        weight: isGen ? 1.5 : 0.5,
      }).bindTooltip(
        `Bus ${bus.id} · ${bus.voltage_kv}kV · ${bus.voltage_magnitude_pu.toFixed(3)}pu`,
        { className: "geo-tip" },
      ).addTo(busLayer);
    }
  }, [gridState]);

  return (
    <div className="relative h-full w-full bg-bg-primary">
      <div ref={containerRef} className="absolute inset-0" style={{ background: "#0b0d10" }} />
      <div className="absolute top-2 left-2 z-[500] bg-bg-secondary/85 border border-border-subtle px-2 py-1 backdrop-blur-sm pointer-events-none">
        <span className="font-mono text-[9px] text-text-secondary uppercase tracking-wider">
          Atlanta Metro · simulated grid over real OpenStreetMap infrastructure
        </span>
      </div>
      <div className="absolute bottom-2 left-2 z-[500] bg-bg-secondary/90 border border-border-subtle px-2.5 py-2 backdrop-blur-sm pointer-events-none">
        <div className="font-mono text-[9px] text-text-muted uppercase tracking-wider mb-1">Legend</div>
        <LegendRow color="#2d4a6b" label="Real transmission (OSM)" line />
        <LegendRow color="#f0a500" label="Real plant / substation" />
        <div className="my-1 border-t border-border-subtle" />
        <LegendRow color="#2f7d5b" label="Sim line — normal flow" line />
        <LegendRow color="#f0a500" label="Sim line — heavy (>70%)" line />
        <LegendRow color="#e53e3e" label="Sim line — overloaded (>90%)" line />
        <LegendRow color="#00c97a" label="Sim bus · generator ringed" />
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
