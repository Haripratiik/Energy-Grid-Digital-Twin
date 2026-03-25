import { useState } from "react";
import { useGridStream } from "./hooks/useGridStream";
import { useOntology } from "./hooks/useOntology";
import Header from "./components/Header";
import GridTopology from "./components/GridTopology";
import OntologyGraph from "./components/OntologyGraph";
import OperatorConsole from "./components/OperatorConsole";

export default function App() {
  const { gridState, connectionStatus } = useGridStream();
  const { ontology, fetchPropagation } = useOntology(
    gridState?.ontology_dirty ?? false
  );
  const [highlightedAsset, setHighlightedAsset] = useState<string | null>(null);

  return (
    <div className="flex flex-col h-screen w-screen bg-bg-primary">
      <Header
        gridState={gridState}
        connectionStatus={connectionStatus}
      />

      <div className="flex flex-1 min-h-0">
        {/* Panel 1: Grid Topology — 40% */}
        <div className="w-[40%] border-r border-border-subtle flex flex-col">
          <GridTopology
            gridState={gridState}
            highlightedAsset={highlightedAsset}
          />
        </div>

        {/* Panel 2: Foundry Ontology — 25% */}
        <div className="w-[25%] border-r border-border-subtle flex flex-col">
          <OntologyGraph
            ontology={ontology}
            gridState={gridState}
            fetchPropagation={fetchPropagation}
          />
        </div>

        {/* Panel 3: Operator Console — 35% */}
        <div className="w-[35%] flex flex-col">
          <OperatorConsole
            gridState={gridState}
            onAssetClick={setHighlightedAsset}
          />
        </div>
      </div>

      {/* Bottom watermark */}
      <div className="fixed bottom-2 right-4 font-mono text-[10px] text-text-muted tracking-widest">
        PALANTIR AIP · FOUNDRY ONTOLOGY · DIGITAL TWIN
      </div>
    </div>
  );
}
