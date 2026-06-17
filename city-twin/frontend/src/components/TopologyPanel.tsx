import { Suspense, lazy, useState } from "react";
import GridTopology from "./GridTopology";
import type { GridState } from "../types/grid";

// MapLibre is ~1 MB — only load it when the operator opens the geographic view.
const GeoMap = lazy(() => import("./GeoMap"));

interface Props {
  gridState: GridState | null;
  highlightedAsset: string | null;
  testingMode?: boolean;
}

type View = "force" | "geo";

export default function TopologyPanel({ gridState, highlightedAsset, testingMode }: Props) {
  const [view, setView] = useState<View>("force");

  return (
    <div className="relative h-full">
      <div className="absolute top-1.5 right-2 z-20 flex border border-border-strong bg-bg-secondary/90 backdrop-blur-sm">
        {(["force", "geo"] as View[]).map((v) => (
          <button
            key={v}
            onClick={() => setView(v)}
            className={`font-mono text-[9px] px-2 py-1 uppercase tracking-wider transition-colors ${
              view === v ? "bg-accent-blue text-white" : "text-text-muted hover:text-text-secondary"
            }`}
          >
            {v === "force" ? "Force" : "Geographic"}
          </button>
        ))}
      </div>
      {view === "force" ? (
        <GridTopology
          gridState={gridState}
          highlightedAsset={highlightedAsset}
          testingMode={testingMode}
        />
      ) : (
        <Suspense
          fallback={
            <div className="flex h-full items-center justify-center font-mono text-[11px] text-text-muted">
              loading map…
            </div>
          }
        >
          <GeoMap gridState={gridState} />
        </Suspense>
      )}
    </div>
  );
}
