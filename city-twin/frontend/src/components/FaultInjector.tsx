import { useState } from "react";
import { API_BASE } from "../hooks/useGridStream";
import type { FaultType } from "../types/grid";

interface FaultOption {
  value: FaultType;
  label: string;
}

const FAULT_TYPES: FaultOption[] = [
  { value: "LINE_TRIP", label: "LINE_TRIP" },
  { value: "TRAFO_TRIP", label: "TRAFO_TRIP" },
  { value: "GEN_DROPOUT", label: "GEN_DROPOUT" },
  { value: "LOAD_SPIKE", label: "LOAD_SPIKE" },
  { value: "GEN_SETPOINT", label: "GEN_SETPOINT" },
];

const LINE_TARGETS = ["0", "5", "10", "12", "15", "20", "25", "30", "40", "50", "60", "70", "80", "90"];
const TRAFO_TARGETS = ["0", "3", "5", "8", "10", "15", "20"];
const GEN_BUS_IDS = ["1", "2", "3", "4", "5", "8", "10", "12", "15", "18", "20", "22"];
const LOAD_BUS_IDS = [
  "6", "7", "9", "11", "13", "14", "16", "17", "19", "21", "23", "24", "25",
  "30", "32", "35", "38",
];

function getTargets(ft: FaultType): string[] {
  switch (ft) {
    case "LINE_TRIP":
      return LINE_TARGETS;
    case "TRAFO_TRIP":
      return TRAFO_TARGETS;
    case "GEN_DROPOUT":
    case "GEN_SETPOINT":
      return GEN_BUS_IDS;
    case "LOAD_SPIKE":
      return LOAD_BUS_IDS;
    default:
      return [];
  }
}

function buildRid(ft: FaultType, target: string): string {
  switch (ft) {
    case "LINE_TRIP":
      return `ri.city-grid.main.transmission-line.${target}`;
    case "TRAFO_TRIP":
      return `ri.city-grid.main.transformer.${target}`;
    case "GEN_DROPOUT":
    case "GEN_SETPOINT":
      return `ri.city-grid.main.generator.${target}`;
    case "LOAD_SPIKE":
      return `ri.city-grid.main.load-bus.${target}`;
    default:
      return "";
  }
}

function targetLabel(ft: FaultType, target: string): string {
  switch (ft) {
    case "LINE_TRIP":
      return `Line ${target}`;
    case "TRAFO_TRIP":
      return `Trafo ${target}`;
    case "GEN_DROPOUT":
    case "GEN_SETPOINT":
      return `Gen Bus ${target}`;
    case "LOAD_SPIKE":
      return `Load Bus ${target}`;
    default:
      return target;
  }
}

const showMagnitude = (ft: FaultType) =>
  ft === "LOAD_SPIKE" || ft === "GEN_SETPOINT";

export default function FaultInjector() {
  const [faultType, setFaultType] = useState<FaultType>("LINE_TRIP");
  const [target, setTarget] = useState(LINE_TARGETS[0]);
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
    } catch {
      /* next poll handles */
    }
    setBusy(false);
  };

  const handleRestore = async () => {
    setBusy(true);
    try {
      await fetch(`${API_BASE}/restore`, { method: "POST" });
    } catch {
      /* next poll handles */
    }
    setBusy(false);
  };

  return (
    <div className="border-t border-border-subtle bg-bg-tertiary p-3">
      <div className="font-mono text-[10px] text-text-muted uppercase tracking-widest mb-2">
        Inject Fault
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        {/* fault type */}
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

        {/* target */}
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
              {targetLabel(faultType, t)}
            </option>
          ))}
        </select>

        {/* magnitude (only for LOAD_SPIKE / GEN_SETPOINT) */}
        {showMagnitude(faultType) && (
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

        {/* inject button */}
        <button
          onClick={handleInject}
          disabled={busy}
          className="font-mono text-[10px] px-3 py-1 bg-accent-red text-white uppercase tracking-wider hover:bg-accent-red/80 disabled:opacity-50 transition-colors"
        >
          Inject
        </button>

        {/* restore button */}
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
