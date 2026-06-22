import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "../hooks/useGridStream";
import type { GridState, ReasoningResult } from "../types/grid";

interface Props {
  gridState: GridState | null;
}

type PanelState = "idle" | "analyzing" | "done";

function parseResponse(text: string) {
  const sections: { title: string; body: string }[] = [];
  const sectionRegex = /(SITUATION|IMMEDIATE ACTIONS|RISK ASSESSMENT)\n/g;
  const parts = text.split(sectionRegex);

  for (let i = 1; i < parts.length; i += 2) {
    sections.push({
      title: parts[i].trim(),
      body: (parts[i + 1] ?? "").trim(),
    });
  }

  if (sections.length === 0) {
    sections.push({ title: "", body: text });
  }

  return sections;
}

export default function ReasoningPanel({ gridState }: Props) {
  const [state, setState] = useState<PanelState>("idle");
  const [result, setResult] = useState<ReasoningResult | null>(null);
  const [displayedText, setDisplayedText] = useState("");
  const [history, setHistory] = useState<ReasoningResult[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const animFrameRef = useRef(0);
  const lastAutoTrigger = useRef(0);

  const typeText = useCallback((fullText: string) => {
    let idx = 0;
    setDisplayedText("");
    const step = () => {
      if (idx < fullText.length) {
        const chunk = Math.min(3, fullText.length - idx);
        idx += chunk;
        setDisplayedText(fullText.slice(0, idx));
        animFrameRef.current = requestAnimationFrame(step);
      }
    };
    animFrameRef.current = requestAnimationFrame(step);
  }, []);

  useEffect(() => {
    if (!gridState) return;
    const critAlerts = gridState.active_alerts?.filter(
      (a) => a.severity === "CRITICAL"
    );
    if (critAlerts && critAlerts.length > 0) {
      const now = Date.now();
      if (now - lastAutoTrigger.current > 5000 && state === "idle") {
        lastAutoTrigger.current = now;
      }
    }
  }, [gridState, state]);

  const handleQuery = async () => {
    setState("analyzing");
    try {
      const r = await fetch(`${API_BASE}/reasoning`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: "" }),
      });
      const data: ReasoningResult = await r.json();
      setResult(data);
      setHistory((prev) => [data, ...prev].slice(0, 5));
      setState("done");
      typeText(data.response_text);
    } catch {
      setState("idle");
    }
  };

  useEffect(() => {
    return () => cancelAnimationFrame(animFrameRef.current);
  }, []);

  const sections = result ? parseResponse(displayedText) : [];

  return (
    <div className="flex flex-col h-full">
      <div className="px-3 py-2 border-b border-border-subtle bg-bg-tertiary flex items-center gap-2">
        <span
          className={`w-1.5 h-1.5 rounded-full ${
            state === "analyzing"
              ? "bg-accent-green pulse-green"
              : state === "done"
                ? "bg-accent-green"
                : "bg-text-muted"
          }`}
        />
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          GRID-AI · Reasoning Engine
        </span>
      </div>

      <div className="flex-1 overflow-y-auto p-3">
        {state === "idle" && (
          <div className="text-center py-6">
            <p className="font-sans text-xs text-text-muted italic mb-3">
              Monitoring ontology for anomalies...
            </p>
            <button
              onClick={handleQuery}
              className="font-mono text-[10px] px-4 py-1.5 border border-accent-blue text-accent-blue uppercase tracking-wider hover:bg-accent-blue/10 transition-colors"
            >
              Query GRID-AI
            </button>
          </div>
        )}

        {state === "analyzing" && (
          <div className="text-center py-6 scan-line-bg">
            <p className="font-mono text-xs text-accent-green animate-pulse">
              ANALYZING ONTOLOGY STATE...
            </p>
          </div>
        )}

        {state === "done" && result && (
          <div className="space-y-3">
            <div className="font-mono text-[9px] text-text-muted">
              {result.trigger_type === "AUTO_CRITICAL"
                ? `Auto-triggered by: ${result.triggered_by_alert_id ?? "CRITICAL alert"}`
                : "Manual query"}
            </div>
            {sections.map((sec, i) => (
              <div key={i}>
                {sec.title && (
                  <div className="font-mono text-[11px] text-text-code mb-1 border-b border-border-subtle pb-1">
                    {sec.title}
                  </div>
                )}
                <div className="font-sans text-[13px] text-text-primary leading-relaxed whitespace-pre-wrap">
                  {sec.body}
                </div>
              </div>
            ))}
            <button
              onClick={() => {
                setState("idle");
                setResult(null);
                setDisplayedText("");
              }}
              className="font-mono text-[10px] px-4 py-1.5 border border-accent-blue text-accent-blue uppercase tracking-wider hover:bg-accent-blue/10 transition-colors mt-2"
            >
              Query GRID-AI
            </button>
          </div>
        )}
      </div>

      {history.length > 0 && (
        <div className="border-t border-border-subtle">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="w-full px-3 py-1.5 font-mono text-[9px] text-text-muted uppercase tracking-wider hover:bg-bg-tertiary text-left"
          >
            {showHistory ? "▾" : "▸"} History ({history.length})
          </button>
          {showHistory && (
            <div className="max-h-32 overflow-y-auto px-3 pb-2 space-y-1">
              {history.map((h) => (
                <div
                  key={h.id}
                  className="font-mono text-[9px] text-text-secondary cursor-pointer hover:text-text-primary"
                  onClick={() => {
                    setResult(h);
                    setDisplayedText(h.response_text);
                    setState("done");
                  }}
                >
                  [{h.trigger_type}] {new Date(h.timestamp).toLocaleTimeString()}{" "}
                  — {h.response_text.slice(0, 60)}...
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
