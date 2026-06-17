import { useState } from "react";
import {
  Panel,
  Group,
  Separator,
} from "react-resizable-panels";
import { useGridStream } from "./hooks/useGridStream";
import { useOntology } from "./hooks/useOntology";
import { useDecisions } from "./hooks/useDecisions";
import { useDemoStatus } from "./hooks/useDemoStatus";
import Header from "./components/Header";
import GridTopology from "./components/GridTopology";
import OntologyGraph from "./components/OntologyGraph";
import OperatorConsole from "./components/OperatorConsole";
import DecisionQueue from "./components/DecisionQueue";
import GeneratorMix from "./components/GeneratorMix";
import DecisionLog from "./components/DecisionLog";
import ContingencyPanel from "./components/ContingencyPanel";
import TwinView from "./components/TwinView";

function ResizeHandleH() {
  return (
    <Separator className="group relative w-[5px] flex items-center justify-center hover:bg-accent-blue/10 transition-colors">
      <div className="w-[1px] h-full bg-border-strong group-hover:bg-accent-blue/50 transition-colors" />
    </Separator>
  );
}

function ResizeHandleV() {
  return (
    <Separator className="group relative h-[5px] flex items-center justify-center hover:bg-accent-blue/10 transition-colors">
      <div className="h-[1px] w-full bg-border-strong group-hover:bg-accent-blue/50 transition-colors" />
    </Separator>
  );
}

export default function App() {
  const { gridState, connectionStatus } = useGridStream();
  const { ontology, fetchPropagation } = useOntology(
    gridState?.ontology_dirty ?? false,
  );
  const { pending, log, mode, approve, reject, revert, toggleMode } =
    useDecisions();
  const demo = useDemoStatus();

  const [highlightedAsset, setHighlightedAsset] = useState<string | null>(
    null,
  );
  const [twinOpen, setTwinOpen] = useState(false);

  return (
    <div className="h-full w-full flex flex-col bg-bg-primary overflow-hidden relative">
      <Header
        gridState={gridState}
        connectionStatus={connectionStatus}
        mode={mode}
        demo={demo}
        onToggleMode={toggleMode}
        onOpenTwin={() => setTwinOpen(true)}
      />

      <TwinView open={twinOpen} onClose={() => setTwinOpen(false)} />

      <Group orientation="horizontal" className="flex-1 min-h-0">
        {/* Panel 1 — Grid Topology */}
        <Panel defaultSize={30} minSize={15}>
          <GridTopology
            gridState={gridState}
            highlightedAsset={highlightedAsset}
          />
        </Panel>

        <ResizeHandleH />

        {/* Panel 2 — Foundry Ontology */}
        <Panel defaultSize={20} minSize={10}>
          <OntologyGraph
            ontology={ontology}
            gridState={gridState}
            fetchPropagation={fetchPropagation}
          />
        </Panel>

        <ResizeHandleH />

        {/* Panel 3 — Operator Console + N-1 Contingency Analysis */}
        <Panel defaultSize={25} minSize={15}>
          <Group orientation="vertical">
            <Panel defaultSize={58} minSize={20}>
              <OperatorConsole
                gridState={gridState}
                onAssetClick={setHighlightedAsset}
              />
            </Panel>

            <ResizeHandleV />

            <Panel defaultSize={42} minSize={15}>
              <ContingencyPanel summary={gridState?.contingency} />
            </Panel>
          </Group>
        </Panel>

        <ResizeHandleH />

        {/* Panel 4 — Decisions + Gen Mix + Audit */}
        <Panel defaultSize={25} minSize={12}>
          <Group orientation="vertical">
            <Panel defaultSize={55} minSize={20}>
              <DecisionQueue
                pending={pending}
                mode={mode}
                onApprove={approve}
                onReject={reject}
                onAssetClick={setHighlightedAsset}
              />
            </Panel>

            <ResizeHandleV />

            <Panel defaultSize={15} minSize={8}>
              <GeneratorMix
                generators={gridState?.generators ?? []}
                totalLoad={gridState?.total_load_mw ?? 0}
              />
            </Panel>

            <ResizeHandleV />

            <Panel defaultSize={30} minSize={10}>
              <DecisionLog decisions={log} onRevert={revert} />
            </Panel>
          </Group>
        </Panel>
      </Group>
    </div>
  );
}
