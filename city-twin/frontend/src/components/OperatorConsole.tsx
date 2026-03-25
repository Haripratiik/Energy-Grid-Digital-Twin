import {
  Panel,
  Group,
  Separator,
} from "react-resizable-panels";
import type { GridState } from "../types/grid";
import AlertFeed from "./AlertFeed";
import ChatPanel from "./ChatPanel";

interface Props {
  gridState: GridState | null;
  onAssetClick?: (rid: string) => void;
}

function ResizeHandleV() {
  return (
    <Separator className="group relative h-[5px] flex items-center justify-center hover:bg-accent-blue/10 transition-colors">
      <div className="h-[1px] w-full bg-border-subtle group-hover:bg-accent-blue/40 transition-colors" />
    </Separator>
  );
}

export default function OperatorConsole({ gridState, onAssetClick }: Props) {
  const alerts = gridState?.active_alerts ?? [];

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-1.5 border-b border-border-strong bg-bg-tertiary shrink-0">
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          <span className="text-accent-blue">03</span> Operations · Alerts & Assistant
        </span>
      </div>

      <Group orientation="vertical" className="flex-1 min-h-0">
        <Panel defaultSize={30} minSize={10}>
          <AlertFeed alerts={alerts} onAssetClick={onAssetClick} />
        </Panel>

        <ResizeHandleV />

        <Panel defaultSize={70} minSize={30}>
          <ChatPanel gridState={gridState} />
        </Panel>
      </Group>
    </div>
  );
}
