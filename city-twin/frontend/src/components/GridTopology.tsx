import { Suspense, lazy } from "react";
import type { GridState } from "../types/grid";
import FaultInjector from "./FaultInjector";
import CustomGridBuilder from "./CustomGridBuilder";

// Leaflet map is loaded only when the operator opens a Geographic view.
const GeoMap = lazy(() => import("./GeoMap"));

// One shared "which grid" selector, driven from App so the ontology panel
// follows the same choice. Three grids, each with its own topology view:
//   synthetic → live simulated 80-bus grid on the Atlanta map
//   real      → real Georgia transmission topology (OSM) on the map
//   custom    → a grid you build & simulate yourself
export type GridSource = "synthetic" | "real" | "custom";

interface Props {
  gridState: GridState | null;
  /** Show the fault-injection sandbox controls (testing mode only). */
  testingMode?: boolean;
  source: GridSource;
  onSourceChange: (s: GridSource) => void;
}

const TABS: { id: GridSource; label: string; title: string }[] = [
  { id: "synthetic", label: "Synthetic", title: "The live simulated 80-bus Atlanta grid" },
  { id: "real", label: "Real GA", title: "Real Georgia transmission (OSM topology, estimated params)" },
  { id: "custom", label: "Custom", title: "Build & simulate your own grid" },
];

export default function GridTopology({
  gridState,
  testingMode = true,
  source,
  onSourceChange,
}: Props) {
  const tabCls = (id: GridSource) =>
    `font-mono text-[9px] px-2 py-0.5 uppercase tracking-wide border transition-colors ${
      source === id
        ? "bg-accent-blue/20 text-accent-blue border-accent-blue/30"
        : "text-text-muted hover:text-text-secondary border-transparent"
    }`;

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-1.5 border-b border-border-strong bg-bg-tertiary flex items-center justify-between gap-2">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest whitespace-nowrap">
          <span className="text-accent-blue">01</span> Grid · Topology
        </span>
        <div className="flex items-center gap-0.5">
          {TABS.map((t) => (
            <button key={t.id} onClick={() => onSourceChange(t.id)} className={tabCls(t.id)} title={t.title}>
              {t.label}
            </button>
          ))}
        </div>
      </div>

      {source === "custom" ? (
        <div className="flex-1 min-h-0 bg-bg-primary">
          <CustomGridBuilder />
        </div>
      ) : (
        <div className="flex-1 min-h-0 bg-bg-primary">
          <Suspense
            fallback={
              <div className="flex h-full items-center justify-center font-mono text-[11px] text-text-muted">
                loading map…
              </div>
            }
          >
            <GeoMap gridState={gridState} source={source} />
          </Suspense>
        </div>
      )}

      {/* Fault injection acts on the live simulated grid only. */}
      {testingMode && source === "synthetic" && <FaultInjector />}
    </div>
  );
}
