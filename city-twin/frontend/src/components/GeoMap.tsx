import { useEffect, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { ATLANTA_BUS_LATLNG } from "../data/atlantaGeo";
import { API_BASE } from "../hooks/useGridStream";
import type { GridState } from "../types/grid";

const ATLANTA_CENTER: [number, number] = [33.75, -84.39];

const STATUS_COLOR: Record<string, string> = {
  normal: "#00c97a",
  warning: "#f0a500",
  critical: "#e53e3e",
};

// Real Atlanta-metro landmarks shown as permanent labels so the map reads as a
// real region. The bus *positions* are real coordinates; the grid wiring is the
// synthetic 80-bus model (see caption).
const LANDMARKS: Record<number, string> = {
  1: "Plant Vogtle · nuclear",
  2: "Buford Dam · hydro",
  3: "Chattahoochee · gas",
  4: "NE Georgia · wind",
  5: "Griffin · solar",
  17: "Hartsfield-Jackson",
  28: "Buckhead",
  29: "Downtown Atlanta",
  37: "Decatur",
  55: "Georgia Tech",
  54: "Emory / CDC",
  66: "Norcross",
};

interface TopoLine {
  index: number;
  from_bus: number;
  to_bus: number;
  voltage_kv: number;
}

interface RealBus {
  id: number;
  lat: number;
  lon: number;
  voltage_kv: number;
  is_source: boolean;
  load_mw: number;
}
interface RealLine {
  from_id: number;
  to_id: number;
  voltage_kv: number;
  length_km: number;
  flow_mw: number;
  loading_pct: number;
}
interface RealGrid {
  buses: RealBus[];
  lines: RealLine[];
  n_buses: number;
  n_lines: number;
  source: string;
}

type Source = "synthetic" | "real";

/** Colour a line by its loading fraction (0..1). */
function lineColor(frac: number): string {
  if (frac > 0.9) return "#e53e3e";
  if (frac > 0.7) return "#f0a500";
  return "#2f7d5b";
}

export default function GeoMap({
  gridState,
  source = "synthetic",
}: {
  gridState: GridState | null;
  source?: Source;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const lineLayerRef = useRef<L.LayerGroup | null>(null);
  const busLayerRef = useRef<L.LayerGroup | null>(null);
  const topoRef = useRef<TopoLine[]>([]);
  const [realGrid, setRealGrid] = useState<RealGrid | null>(null);
  // Which source the map is currently framed (fitBounds) for; lets us re-frame
  // on source change without resetting the user's zoom on every live poll.
  const fittedRef = useRef<Source | null>(null);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;
    const map = L.map(containerRef.current, {
      center: ATLANTA_CENTER, zoom: 10, zoomControl: true, preferCanvas: true,
    });
    mapRef.current = map;

    L.tileLayer("https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png", {
      subdomains: "abcd", maxZoom: 19, attribution: "© OpenStreetMap © CARTO",
    }).addTo(map);

    // Real OSM transmission infrastructure (faint), purely as geographic context.
    fetch("/atlanta_grid_infra.geojson")
      .then((r) => r.json())
      .then((geo) => {
        if (!mapRef.current) return;
        L.geoJSON(geo, {
          style: () => ({ color: "#2d4a6b", weight: 1, opacity: 0.35 }),
          pointToLayer: (feature, latlng) =>
            feature.properties?.power === "plant"
              ? L.circleMarker(latlng, { radius: 4, color: "#0b0d10", weight: 1, fillColor: "#6b7686", fillOpacity: 0.5 })
              : L.circleMarker(latlng, { radius: 1.6, stroke: false, fillColor: "#436085", fillOpacity: 0.35 }),
        }).addTo(map);
      })
      .catch(() => undefined);

    lineLayerRef.current = L.layerGroup().addTo(map);
    busLayerRef.current = L.layerGroup().addTo(map);

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

  // Lazily fetch the real Georgia grid the first time it's selected.
  useEffect(() => {
    if (source !== "real" || realGrid) return;
    fetch(`${API_BASE}/real-grid`).then((r) => r.json()).then(setRealGrid).catch(() => undefined);
  }, [source, realGrid]);

  // Wipe both layers the instant the source changes, so the previous grid's
  // geometry can never linger under the new caption (e.g. if gridState is briefly
  // null when switching real → synthetic).
  useEffect(() => {
    lineLayerRef.current?.clearLayers();
    busLayerRef.current?.clearLayers();
  }, [source]);

  // ---- Synthetic: live simulated grid drawn over the real basemap ----
  useEffect(() => {
    if (source !== "synthetic") return;
    const map = mapRef.current;
    const lineLayer = lineLayerRef.current;
    const busLayer = busLayerRef.current;
    if (!map || !lineLayer || !busLayer) return;

    if (fittedRef.current !== "synthetic") {
      map.fitBounds(L.latLngBounds(Object.values(ATLANTA_BUS_LATLNG) as [number, number][]).pad(0.08));
      fittedRef.current = "synthetic";
    }
    if (!gridState) return;

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
      const marker = L.circleMarker(latlng, {
        radius: tier === 3 ? 6 : tier === 2 ? 4 : 2.6,
        fillColor: STATUS_COLOR[bus.status] ?? "#8a919e",
        fillOpacity: 0.92, color: isGen ? "#ffffff" : "#0b0d10", weight: isGen ? 1.5 : 0.5,
      });
      const name = LANDMARKS[bus.id];
      if (name) {
        marker.bindTooltip(name, {
          permanent: true, direction: "right", offset: [7, 0], className: "geo-label",
        });
      } else {
        marker.bindTooltip(
          `Bus ${bus.id} · ${bus.voltage_kv}kV · ${bus.voltage_magnitude_pu.toFixed(3)}pu`,
          { className: "geo-tip" },
        );
      }
      marker.addTo(busLayer);
    }
  }, [gridState, source]);

  // ---- Real Georgia transmission grid (static, real coords + estimated params) ----
  useEffect(() => {
    if (source !== "real") return;
    const map = mapRef.current;
    const lineLayer = lineLayerRef.current;
    const busLayer = busLayerRef.current;
    if (!map || !lineLayer || !busLayer || !realGrid) return;

    // Worst incident-line loading per bus → bus stress colour.
    const stress = new Map<number, number>();
    for (const ln of realGrid.lines) {
      for (const end of [ln.from_id, ln.to_id]) {
        stress.set(end, Math.max(stress.get(end) ?? 0, ln.loading_pct));
      }
    }
    const pos = new Map(realGrid.buses.map((b) => [b.id, [b.lat, b.lon] as [number, number]]));

    lineLayer.clearLayers();
    for (const ln of realGrid.lines) {
      const a = pos.get(ln.from_id);
      const b = pos.get(ln.to_id);
      if (!a || !b) continue;
      const frac = ln.loading_pct / 100;
      L.polyline([a, b], {
        color: lineColor(frac),
        weight: (ln.voltage_kv >= 500 ? 2.4 : ln.voltage_kv >= 230 ? 1.6 : 0.9) + Math.min(frac, 1) * 1.0,
        opacity: 0.45 + Math.min(frac, 1) * 0.4,
      }).bindTooltip(
        `${ln.voltage_kv}kV · ${Math.round(ln.length_km)}km · ${ln.loading_pct.toFixed(0)}% loaded`,
        { className: "geo-tip" },
      ).addTo(lineLayer);
    }

    busLayer.clearLayers();
    for (const bus of realGrid.buses) {
      const s = stress.get(bus.id) ?? 0;
      const stressColor = s > 90 ? "#e53e3e" : s > 70 ? "#f0a500" : "#3f8f6a";
      const tier = bus.voltage_kv >= 500 ? 3 : bus.voltage_kv >= 230 ? 2 : 1;
      L.circleMarker([bus.lat, bus.lon], {
        radius: bus.is_source ? 6 : tier === 3 ? 4.5 : tier === 2 ? 3.2 : 2,
        fillColor: bus.is_source ? "#00c97a" : stressColor,
        fillOpacity: 0.92,
        color: bus.is_source ? "#ffffff" : "#0b0d10",
        weight: bus.is_source ? 1.5 : 0.5,
      }).bindTooltip(
        bus.is_source
          ? `Source · ${bus.voltage_kv}kV`
          : `Substation ${bus.id} · ${bus.voltage_kv}kV${bus.load_mw ? ` · ${bus.load_mw.toFixed(0)}MW` : ""}`,
        { className: "geo-tip" },
      ).addTo(busLayer);
    }

    if (fittedRef.current !== "real") {
      const bounds = L.latLngBounds(realGrid.buses.map((b) => [b.lat, b.lon] as [number, number]));
      if (bounds.isValid()) map.fitBounds(bounds.pad(0.06));
      fittedRef.current = "real";
    }
  }, [realGrid, source]);

  const isReal = source === "real";

  return (
    <div className="relative h-full w-full bg-bg-primary">
      <div ref={containerRef} className="absolute inset-0" style={{ background: "#0b0d10" }} />

      <div className="absolute top-2 left-2 z-[500] bg-bg-secondary/85 border border-border-subtle px-2 py-1 backdrop-blur-sm pointer-events-none max-w-[72%]">
        <span className="font-mono text-[9px] text-text-secondary uppercase tracking-wider">
          {isReal
            ? "Real Georgia transmission · OSM topology · estimated electrical params (CEII)"
            : "Synthetic 80-bus grid · illustrative Atlanta-metro coordinates · live over real OSM infrastructure"}
        </span>
      </div>

      <div className="absolute bottom-2 left-2 z-[500] bg-bg-secondary/90 border border-border-subtle px-2.5 py-2 backdrop-blur-sm pointer-events-none">
        <div className="font-mono text-[9px] text-text-muted uppercase tracking-wider mb-1">Legend</div>
        {isReal ? (
          <>
            <LegendRow color="#00c97a" label="Source substation (ringed white)" />
            <LegendRow color="#3f8f6a" label="Substation — by worst incident loading" />
            <div className="my-1 border-t border-border-subtle" />
            <LegendRow color="#2f7d5b" label="Line — normal flow" line />
            <LegendRow color="#f0a500" label="Line — heavy (>70%)" line />
            <LegendRow color="#e53e3e" label="Line — overloaded (>90%)" line />
          </>
        ) : (
          <>
            <LegendRow color="#6b7686" label="Real OSM infrastructure (context)" />
            <div className="my-1 border-t border-border-subtle" />
            <LegendRow color="#00c97a" label="Bus — nominal (generators ringed white)" />
            <LegendRow color="#2f7d5b" label="Line — normal flow" line />
            <LegendRow color="#f0a500" label="Line — heavy (>70%)" line />
            <LegendRow color="#e53e3e" label="Line — overloaded (>90%)" line />
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
