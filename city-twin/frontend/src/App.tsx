import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import GridLayout, { type Layout } from "react-grid-layout";
import "react-grid-layout/css/styles.css";
import "react-resizable/css/styles.css";
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

const LAYOUT_KEY = "gridtwin.layout.v1";

const DEFAULT_LAYOUT: Layout[] = [
  { i: "topology", x: 0, y: 0, w: 4, h: 20, minW: 2, minH: 8 },
  { i: "ontology", x: 4, y: 0, w: 3, h: 10, minW: 2, minH: 5 },
  { i: "contingency", x: 4, y: 10, w: 3, h: 10, minW: 2, minH: 5 },
  { i: "operator", x: 7, y: 0, w: 5, h: 12, minW: 3, minH: 6 },
  { i: "decisions", x: 7, y: 12, w: 5, h: 8, minW: 3, minH: 5 },
  { i: "genmix", x: 0, y: 20, w: 4, h: 6, minW: 2, minH: 4 },
  { i: "log", x: 4, y: 20, w: 8, h: 6, minW: 3, minH: 4 },
];

function loadLayout(): Layout[] {
  try {
    const raw = localStorage.getItem(LAYOUT_KEY);
    if (raw) return JSON.parse(raw) as Layout[];
  } catch {
    /* fall through to default */
  }
  return DEFAULT_LAYOUT;
}

function PanelCard({ children }: { children: ReactNode }) {
  return (
    <div className="h-full flex flex-col border border-border-strong bg-bg-secondary overflow-hidden">
      <div
        className="panel-drag shrink-0 h-4 flex items-center justify-center bg-bg-tertiary border-b border-border-subtle cursor-grab active:cursor-grabbing select-none hover:bg-bg-elevated transition-colors"
        title="Drag to move · resize from the corner"
      >
        <span className="font-mono text-[10px] text-text-muted leading-none tracking-[0.3em]">⠿⠿⠿</span>
      </div>
      <div className="flex-1 min-h-0 overflow-hidden">{children}</div>
    </div>
  );
}

export default function App() {
  const { gridState, connectionStatus } = useGridStream();
  const { ontology } = useOntology(gridState?.ontology_dirty ?? false);
  const { pending, log, mode, approve, reject, revert, toggleMode } = useDecisions();
  const demo = useDemoStatus();

  const [highlightedAsset, setHighlightedAsset] = useState<string | null>(null);
  const [twinOpen, setTwinOpen] = useState(false);
  const [appMode, setAppMode] = useState<"operations" | "testing">("operations");
  const [layout, setLayout] = useState<Layout[]>(loadLayout);
  // One shared "which grid" selector that drives BOTH the topology panel and the
  // ontology panel — they are two views of the same grid, not separate choices.
  const [gridSource, setGridSource] = useState<"synthetic" | "real" | "custom">("synthetic");

  // Measure the grid container width ourselves (more reliable than WidthProvider
  // inside a flex/overflow container under React StrictMode).
  const gridWrapRef = useRef<HTMLDivElement>(null);
  const [gridWidth, setGridWidth] = useState(0);
  useEffect(() => {
    const el = gridWrapRef.current;
    if (!el) return;
    const measure = () => setGridWidth(el.clientWidth);
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);

  const onLayoutChange = useCallback((next: Layout[]) => {
    setLayout(next);
    try {
      localStorage.setItem(LAYOUT_KEY, JSON.stringify(next));
    } catch {
      /* ignore quota errors */
    }
  }, []);

  const resetLayout = useCallback(() => {
    localStorage.removeItem(LAYOUT_KEY);
    setLayout(DEFAULT_LAYOUT.map((l) => ({ ...l })));
  }, []);

  return (
    <div className="h-full w-full flex flex-col bg-bg-primary overflow-hidden relative">
      <Header
        gridState={gridState}
        connectionStatus={connectionStatus}
        mode={mode}
        demo={demo}
        onToggleMode={toggleMode}
        onOpenTwin={() => setTwinOpen(true)}
        appMode={appMode}
        onToggleAppMode={() => setAppMode((m) => (m === "operations" ? "testing" : "operations"))}
        onResetLayout={resetLayout}
      />

      <TwinView open={twinOpen} onClose={() => setTwinOpen(false)} />

      <div ref={gridWrapRef} className="flex-1 min-h-0 overflow-auto p-1.5">
        {gridWidth > 0 && (
        <GridLayout
          className="layout"
          width={gridWidth - 12}
          layout={layout}
          cols={12}
          rowHeight={28}
          margin={[6, 6]}
          containerPadding={[0, 0]}
          draggableHandle=".panel-drag"
          onLayoutChange={onLayoutChange}
          compactType="vertical"
          isDraggable
          isResizable
          resizeHandles={["se"]}
        >
          <div key="topology">
            <PanelCard>
              <GridTopology
                gridState={gridState}
                testingMode={appMode === "testing"}
                source={gridSource}
                onSourceChange={setGridSource}
              />
            </PanelCard>
          </div>
          <div key="ontology">
            <PanelCard>
              <OntologyGraph
                ontology={ontology}
                source={gridSource}
                highlightedAsset={highlightedAsset}
              />
            </PanelCard>
          </div>
          <div key="contingency">
            <PanelCard>
              <ContingencyPanel summary={gridState?.contingency} />
            </PanelCard>
          </div>
          <div key="operator">
            <PanelCard>
              <OperatorConsole gridState={gridState} onAssetClick={setHighlightedAsset} />
            </PanelCard>
          </div>
          <div key="decisions">
            <PanelCard>
              <DecisionQueue
                pending={pending}
                mode={mode}
                onApprove={approve}
                onReject={reject}
                onAssetClick={setHighlightedAsset}
              />
            </PanelCard>
          </div>
          <div key="genmix">
            <PanelCard>
              <GeneratorMix
                generators={gridState?.generators ?? []}
                totalLoad={gridState?.total_load_mw ?? 0}
              />
            </PanelCard>
          </div>
          <div key="log">
            <PanelCard>
              <DecisionLog decisions={log} onRevert={revert} />
            </PanelCard>
          </div>
        </GridLayout>
        )}
      </div>
    </div>
  );
}
