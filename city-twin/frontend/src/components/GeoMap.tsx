import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { BUS_GEO_MAP } from "../data/cityGeo";
import type { GridState } from "../types/grid";

// Atlanta metro bbox the real infrastructure was fetched for (S, W, N, E).
const BBOX = { s: 33.55, w: -84.66, n: 34.06, e: -84.05 };
const SVG_W = 900;
const SVG_H = 700;

/** Map the synthetic 900×700 layout onto real Atlanta coordinates. */
function toLngLat(x: number, y: number): [number, number] {
  const lng = BBOX.w + (x / SVG_W) * (BBOX.e - BBOX.w);
  const lat = BBOX.n - (y / SVG_H) * (BBOX.n - BBOX.s);
  return [lng, lat];
}

const STATUS_COLOR: Record<string, string> = {
  normal: "#00c97a",
  warning: "#f0a500",
  critical: "#e53e3e",
};

function busFeatures(state: GridState | null) {
  const feats: GeoJSON.Feature[] = [];
  if (!state) return { type: "FeatureCollection", features: feats } as GeoJSON.FeatureCollection;
  const genBuses = new Set(state.generators.map((g) => g.bus_id));
  for (const b of state.buses) {
    const geo = BUS_GEO_MAP.get(b.id);
    if (!geo) continue;
    feats.push({
      type: "Feature",
      properties: {
        id: b.id,
        status: b.status,
        color: STATUS_COLOR[b.status] ?? "#8a919e",
        tier: b.voltage_kv >= 300 ? 3 : b.voltage_kv >= 100 ? 2 : 1,
        is_gen: genBuses.has(b.id) ? 1 : 0,
      },
      geometry: { type: "Point", coordinates: toLngLat(geo.x, geo.y) },
    });
  }
  return { type: "FeatureCollection", features: feats } as GeoJSON.FeatureCollection;
}

export default function GeoMap({ gridState }: { gridState: GridState | null }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const loadedRef = useRef(false);

  // Initialise the map once.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = new maplibregl.Map({
      container: containerRef.current,
      style: {
        version: 8,
        sources: {
          carto: {
            type: "raster",
            tiles: [
              "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
              "https://b.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
              "https://c.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png",
            ],
            tileSize: 256,
            attribution: "© OpenStreetMap © CARTO",
          },
        },
        layers: [{ id: "carto", type: "raster", source: "carto" }],
      },
      center: [(BBOX.w + BBOX.e) / 2, (BBOX.s + BBOX.n) / 2],
      zoom: 9,
      attributionControl: false,
    });
    mapRef.current = map;
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    map.addControl(new maplibregl.AttributionControl({ compact: true }), "bottom-right");

    map.on("load", () => {
      // Real transmission infrastructure (OpenStreetMap).
      map.addSource("infra", { type: "geojson", data: "/atlanta_grid_infra.geojson" });
      map.addLayer({
        id: "infra-lines",
        type: "line",
        source: "infra",
        filter: ["==", ["get", "power"], "line"],
        paint: { "line-color": "#3a6ea5", "line-width": 1, "line-opacity": 0.55 },
      });
      map.addLayer({
        id: "infra-substations",
        type: "circle",
        source: "infra",
        filter: ["==", ["get", "power"], "substation"],
        paint: { "circle-radius": 2.5, "circle-color": "#5b7fa6", "circle-opacity": 0.6 },
      });
      map.addLayer({
        id: "infra-plants",
        type: "circle",
        source: "infra",
        filter: ["==", ["get", "power"], "plant"],
        paint: {
          "circle-radius": 5,
          "circle-color": "#f0a500",
          "circle-stroke-color": "#0b0d10",
          "circle-stroke-width": 1,
        },
      });

      // Simulated grid — live bus states.
      map.addSource("sim-buses", { type: "geojson", data: busFeatures(gridState) });
      map.addLayer({
        id: "sim-bus-glow",
        type: "circle",
        source: "sim-buses",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "tier"], 1, 5, 3, 11],
          "circle-color": ["get", "color"],
          "circle-opacity": 0.18,
          "circle-blur": 0.8,
        },
      });
      map.addLayer({
        id: "sim-bus",
        type: "circle",
        source: "sim-buses",
        paint: {
          "circle-radius": ["interpolate", ["linear"], ["get", "tier"], 1, 2.5, 3, 5.5],
          "circle-color": ["get", "color"],
          "circle-stroke-color": ["case", ["==", ["get", "is_gen"], 1], "#ffffff", "#0b0d10"],
          "circle-stroke-width": ["case", ["==", ["get", "is_gen"], 1], 1.5, 0.5],
        },
      });
      loadedRef.current = true;
    });

    return () => {
      map.remove();
      mapRef.current = null;
      loadedRef.current = false;
    };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  // Push live bus state into the map whenever it changes.
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !loadedRef.current) return;
    const src = map.getSource("sim-buses") as maplibregl.GeoJSONSource | undefined;
    src?.setData(busFeatures(gridState));
  }, [gridState]);

  return (
    <div className="flex flex-col h-full bg-bg-primary">
      <div className="px-3 py-1.5 border-b border-border-strong bg-bg-tertiary flex items-center justify-between">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          Geographic View · Atlanta Metro
        </span>
        <span className="font-mono text-[9px] text-text-muted">real grid · OpenStreetMap</span>
      </div>
      <div className="relative flex-1 min-h-0">
        <div ref={containerRef} className="absolute inset-0" />
        {/* legend */}
        <div className="absolute bottom-2 left-2 z-10 bg-bg-secondary/90 border border-border-subtle px-2.5 py-2 backdrop-blur-sm">
          <div className="font-mono text-[9px] text-text-muted uppercase tracking-wider mb-1">
            Legend
          </div>
          <LegendRow color="#3a6ea5" label="Real transmission (OSM)" line />
          <LegendRow color="#5b7fa6" label="Real substation" />
          <LegendRow color="#f0a500" label="Power plant" />
          <div className="my-1 border-t border-border-subtle" />
          <LegendRow color="#00c97a" label="Sim bus — normal" />
          <LegendRow color="#f0a500" label="Sim bus — warning" />
          <LegendRow color="#e53e3e" label="Sim bus — critical" />
          <LegendRow color="#ffffff" label="Generator (ringed)" />
        </div>
      </div>
    </div>
  );
}

function LegendRow({ color, label, line }: { color: string; label: string; line?: boolean }) {
  return (
    <div className="flex items-center gap-1.5 py-0.5">
      <span
        className="inline-block shrink-0"
        style={
          line
            ? { width: 12, height: 2, background: color }
            : { width: 8, height: 8, borderRadius: 9999, background: color }
        }
      />
      <span className="font-mono text-[9px] text-text-secondary">{label}</span>
    </div>
  );
}
