import { useState } from "react";
import { API_BASE } from "../hooks/useGridStream";
import type { FaultType } from "../types/grid";

const FAULT_TYPES: { value: FaultType; label: string }[] = [
  { value: "LINE_TRIP", label: "LINE_TRIP" },
  { value: "GEN_DROPOUT", label: "GEN_DROPOUT" },
  { value: "LOAD_SPIKE", label: "LOAD_SPIKE" },
];

const LINE_TARGETS = [
  "1-4", "4-5", "5-6", "3-6", "6-7", "7-8", "8-2", "8-9", "9-4",
];
const GEN_TARGETS = ["1", "2", "3"];
const LOAD_TARGETS = ["4", "5", "6", "7", "8", "9"];

function getTargets(faultType: FaultType): string[] {
  switch (faultType) {
    case "LINE_TRIP":
      return LINE_TARGETS;
    case "GEN_DROPOUT":
      return GEN_TARGETS;
    case "LOAD_SPIKE":
      return LOAD_TARGETS;
    default:
      return [];
  }
}

function buildRid(faultType: FaultType, target: string): string {
  switch (faultType) {
    case "LINE_TRIP":
      return `ri.grid-asset.main.transmission-line.${target}`;
    case "GEN_DROPOUT":
      return `ri.grid-asset.main.generator.${target}`;
    case "LOAD_SPIKE":
      return `ri.grid-asset.main.load-bus.${target}`;
    default:
      return "";
  }
}

export default function FaultInjector() {
  const [faultType, setFaultType] = useState<FaultType>("LINE_TRIP");
  const [target, setTarget] = useState("1-4");
  const [magnitude, setMagnitude] = useState("80");
  const [busy, setBusy] = useState(false);

  const targets = getTargets(faultType);

  const handleInject = async () => {
    setBusy(true);
    try {
      await fetch(`${API_BASE}/fault`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: faultType,
          target_rid: buildRid(faultType, target),
          magnitude_mw: parseFloat(magnitude) || 0,
        }),
      });
    } catch {}
    setBusy(false);
  };

  const handleRestore = async () => {
    setBusy(true);
    try {
      await fetch(`${API_BASE}/restore`, { method: "POST" });
    } catch {}
    setBusy(false);
  };

  return (
    <div className="border-t border-border-subtle bg-bg-tertiary p-3">
      <div className="font-mono text-[10px] text-text-muted uppercase tracking-widest mb-2">
        Inject Fault
      </div>
      <div className="flex items-center gap-2 flex-wrap">
        <label className="font-mono text-[10px] text-text-secondary">
          Type:
        </label>
        <select
          value={faultType}
          onChange={(e) => {
            const ft = e.target.value as FaultType;
            setFaultType(ft);
            setTarget(getTargets(ft)[0] ?? "");
          }}
          className="bg-bg-elevated border border-border-subtle text-text-primary font-mono text-xs px-2 py-1 outline-none focus:border-accent-blue"
        >
          {FAULT_TYPES.map((ft) => (
            <option key={ft.value} value={ft.value}>
              {ft.label}
            </option>
          ))}
        </select>

        <label className="font-mono text-[10px] text-text-secondary">
          Target:
        </label>
        <select
          value={target}
          onChange={(e) => setTarget(e.target.value)}
          className="bg-bg-elevated border border-border-subtle text-text-primary font-mono text-xs px-2 py-1 outline-none focus:border-accent-blue"
        >
          {targets.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>

        {faultType === "LOAD_SPIKE" && (
          <>
            <label className="font-mono text-[10px] text-text-secondary">
              MW:
            </label>
            <input
              type="number"
              value={magnitude}
              onChange={(e) => setMagnitude(e.target.value)}
              className="w-16 bg-bg-elevated border border-border-subtle text-text-primary font-mono text-xs px-2 py-1 outline-none focus:border-accent-blue"
            />
          </>
        )}

        <button
          onClick={handleInject}
          disabled={busy}
          className="font-mono text-[10px] px-3 py-1 bg-accent-red text-white uppercase tracking-wider hover:bg-accent-red/80 disabled:opacity-50 transition-colors"
        >
          Inject
        </button>

        <button
          onClick={handleRestore}
          disabled={busy}
          className="font-mono text-[10px] px-3 py-1 bg-border-strong text-text-secondary uppercase tracking-wider hover:bg-border-subtle disabled:opacity-50 transition-colors"
        >
          Restore Nominal
        </button>
      </div>
    </div>
  );
}
