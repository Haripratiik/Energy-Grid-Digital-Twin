import { useEffect, useState } from "react";
import { motion, AnimatePresence, useReducedMotion } from "framer-motion";
import TwinTab from "./analytics/TwinTab";
import StateEstimationTab from "./analytics/StateEstimationTab";
import FrequencyTab from "./analytics/FrequencyTab";
import PerformanceTab from "./analytics/PerformanceTab";

interface Props {
  open: boolean;
  onClose: () => void;
}

type TabId = "twin" | "estimation" | "frequency" | "performance";

const TABS: { id: TabId; label: string }[] = [
  { id: "twin", label: "Digital Twin (UKF)" },
  { id: "estimation", label: "State Estimation" },
  { id: "frequency", label: "Inertia & Grid-Forming" },
  { id: "performance", label: "Fast N-1 (LODF)" },
];

export default function TwinView({ open, onClose }: Props) {
  const reduce = useReducedMotion();
  const [tab, setTab] = useState<TabId>("twin");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    if (open) window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <AnimatePresence>
      {open && (
        <motion.div
          className="fixed inset-0 z-[1000] flex items-center justify-center bg-black/60 p-4"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.15 }}
          onClick={onClose}
        >
          <motion.div
            className="w-full max-w-5xl max-h-[92vh] flex flex-col bg-bg-secondary border border-border-strong shadow-2xl"
            initial={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.97, y: 8 }}
            animate={reduce ? { opacity: 1 } : { opacity: 1, scale: 1, y: 0 }}
            exit={reduce ? { opacity: 0 } : { opacity: 0, scale: 0.98 }}
            transition={{ duration: 0.2, ease: "easeOut" }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* header */}
            <div className="flex items-center justify-between px-4 py-3 border-b border-border-strong">
              <div>
                <h2 className="font-mono text-[13px] text-text-primary tracking-wide">
                  Grid Analytics · Digital Twin & Estimation
                </h2>
                <p className="font-mono text-[10px] text-text-muted mt-0.5">
                  Advanced power-system analysis — validated against benchmarks & analytical results
                </p>
              </div>
              <button
                onClick={onClose}
                aria-label="Close analytics view"
                className="font-mono text-[11px] px-2 py-1 border border-border-strong text-text-secondary hover:bg-bg-elevated transition-colors"
              >
                ESC ✕
              </button>
            </div>

            {/* tab bar */}
            <div className="flex border-b border-border-strong bg-bg-tertiary overflow-x-auto">
              {TABS.map((t) => (
                <button
                  key={t.id}
                  onClick={() => setTab(t.id)}
                  className={`font-mono text-[10px] px-4 py-2 uppercase tracking-wider whitespace-nowrap border-b-2 transition-colors ${
                    tab === t.id
                      ? "border-accent-blue text-text-primary bg-bg-secondary"
                      : "border-transparent text-text-muted hover:text-text-secondary"
                  }`}
                >
                  {t.label}
                </button>
              ))}
            </div>

            {/* body */}
            <div className="p-4 overflow-y-auto">
              {tab === "twin" && <TwinTab />}
              {tab === "estimation" && <StateEstimationTab />}
              {tab === "frequency" && <FrequencyTab />}
              {tab === "performance" && <PerformanceTab />}
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>
  );
}
