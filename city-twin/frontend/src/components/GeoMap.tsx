import { useEffect, useRef } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { BUS_GEO_MAP } from "../data/cityGeo";
import type { GridState } from "../types/grid";

// Atlanta metro bbox the real infrastructure was fetched for (S, W, N, E).
const BBOX = { s: 33.55, w: -84.66, n: 34.06, e: -84.05 };
const SVG_W = 900;
const SVG_H = 700;

/** Map the synthetic 900×700 layout onto real Atlanta coordinates → [lat, lng]. */
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

export default function GeoMap({ gridState }: { gridState: GridState | null }) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const busLayerRef = useRef<L.LayerGroup | null>(null);

  // Init map once.
  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, {
      center: [(BBOX.s + BBOX.n) / 2, (BBOX.w + BBOX.e) / 2],
      zoom: 10,
      zoomControl: true,
      attributionControl: true,
      preferCanvas: true,
    });
    mapRef.current = map;

    L.tileLayer(
      "https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png",
      {
        subdomains: "abcd",
        maxZoom: 19,
        attribution: "© OpenStreetMap © CARTO",
      },
    ).addTo(map);

    // Real transmission infrastructure (OpenStreetMap GeoJSON).
    fetch("/atlanta_grid_infra.geojson")
      .then((r) => r.json())
      .then((geo) => {
        if (!mapRef.current) return;
        L.geoJSON(geo, {
          style: () => ({ color: "#3a6ea5", weight: 1, opacity: 0.55 }),
          pointToLayer: (feature, latlng) => {
            const power = feature.properties?.power;
            if (power === "plant") {
              return L.circleMarker(latlng, {
                radius: 5, color: "#0b0d10", weight: 1,
                fillColor: "#f0a500", fillOpacity: 0.95,
              });
            }
            return L.circleMarker(latlng, {
              radius: 2.5, stroke: false, fillColor: "#5b7fa6", fillOpacity: 0.6,
            });
          },
        }).addTo(map);
      })
      .catch(() => undefined);

    busLayerRef.current = L.layerGroup().addTo(map);

    // Leaflet needs the container sized; invalidate now and on any resize.
    setTimeout(() => map.invalidateSize(), 0);
    const ro = new ResizeObserver(() => map.invalidateSize());
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      map.remove();
      mapRef.current = null;
      busLayerRef.current = null;
    };
  }, []);

  // Push live simulated-bus states into the map whenever state changes.
  useEffect(() => {
    const layer = busLayerRef.current;
    if (!layer || !gridState) return;
    layer.clearLayers();
    const genBuses = new Set(gridState.generators.map((g) => g.bus_id));
    for (const b of gridState.buses) {
      const geo = BUS_GEO_MAP.get(b.id);
      if (!geo) continue;
      const isGen = genBuses.has(b.id);
      const tier = b.voltage_kv >= 300 ? 3 : b.voltage_kv >= 100 ? 2 : 1;
      L.circleMarker(toLatLng(geo.x, geo.y), {
        radius: tier === 3 ? 6 : tier === 2 ? 4.5 : 3,
        fillColor: STATUS_COLOR[b.status] ?? "#8a919e",
        fillOpacity: 0.9,
        color: isGen ? "#ffffff" : "#0b0d10",
        weight: isGen ? 1.5 : 0.5,
      }).addTo(layer);
    }
  }, [gridState]);

  return (
    <div className="relative h-full w-full bg-bg-primary">
      <div ref={containerRef} className="absolute inset-0" style={{ background: "#0b0d10" }} />
      <div className="absolute top-2 left-2 z-[500] bg-bg-secondary/85 border border-border-subtle px-2 py-1 backdrop-blur-sm pointer-events-none">
        <span className="font-mono text-[9px] text-text-secondary uppercase tracking-wider">
          Atlanta Metro · real grid (OpenStreetMap)
        </span>
      </div>
      <div className="absolute bottom-2 left-2 z-[500] bg-bg-secondary/90 border border-border-subtle px-2.5 py-2 backdrop-blur-sm pointer-events-none">
        <div className="font-mono text-[9px] text-text-muted uppercase tracking-wider mb-1">Legend</div>
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
