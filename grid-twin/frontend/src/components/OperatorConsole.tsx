import type { GridState } from "../types/grid";
import MetricsBar from "./MetricsBar";
import AlertFeed from "./AlertFeed";
import ReasoningPanel from "./ReasoningPanel";

interface Props {
  gridState: GridState | null;
  onAssetClick?: (rid: string) => void;
}

export default function OperatorConsole({ gridState, onAssetClick }: Props) {
  const alerts = gridState?.active_alerts ?? [];

  return (
    <div className="flex flex-col h-full">
      {/* 3a: System Metrics — top ~22% */}
      <div className="shrink-0">
        <MetricsBar gridState={gridState} />
      </div>

      {/* 3b: Alert Feed — middle ~33% */}
      <div className="h-[33%] min-h-0 border-b border-border-subtle">
        <AlertFeed alerts={alerts} onAssetClick={onAssetClick} />
      </div>

      {/* 3c: GRID-AI Reasoning — bottom ~45% */}
      <div className="flex-1 min-h-0">
        <ReasoningPanel gridState={gridState} />
      </div>
    </div>
  );
}
