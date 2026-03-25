import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE } from "../hooks/useGridStream";
import type { GridState, ReasoningResult, ProposedAction, RiskLevel } from "../types/grid";

interface Props {
  gridState: GridState | null;
}

type PanelState = "idle" | "analyzing" | "done";

// ── Presets ──────────────────────────────────────────────────────────────────

const PRESETS = [
  "Summarize grid health",
  "What should I worry about?",
  "Explain the frequency trend",
  "Are any lines at risk?",
] as const;

// ── Risk badge styling ───────────────────────────────────────────────────────

const RISK_BG: Record<string, string> = {
  ADVISORY: "bg-accent-blue/15 text-accent-blue border-accent-blue/30",
  CONTROLLED:
    "bg-accent-yellow/15 text-accent-yellow border-accent-yellow/30",
  CRITICAL: "bg-accent-red/15 text-accent-red border-accent-red/30",
  EMERGENCY: "bg-accent-red text-white border-accent-red",
};

// ── Helpers ──────────────────────────────────────────────────────────────────

function ridShort(rid: string): string {
  const parts = rid.split(".");
  const type = parts[parts.length - 2] ?? "";
  const id = parts[parts.length - 1] ?? "";
  if (type === "transmission-line") return `Line ${id}`;
  if (type === "generator") return `Gen ${id}`;
  if (type === "load-bus") return `Bus ${id}`;
  if (type === "transformer") return `Trafo ${id}`;
  if (type === "substation") return `Sub ${id}`;
  return id;
}

function confidenceColor(pct: number): string {
  if (pct >= 80) return "text-accent-green";
  if (pct >= 60) return "text-accent-yellow";
  return "text-accent-red";
}

function cascadeColor(p: number): string {
  if (p > 0.5) return "text-accent-red";
  if (p > 0.2) return "text-accent-yellow";
  return "text-accent-green";
}

// ── Action Card ──────────────────────────────────────────────────────────────

function ActionCard({ action }: { action: ProposedAction }) {
  const risk: RiskLevel = action.risk_level ?? "ADVISORY";
  const confPct = (action.confidence * 100).toFixed(0);

  return (
    <div className="bg-bg-secondary border border-border-subtle p-2.5 space-y-1.5">
      {/* row 1: badges + type + target */}
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className={`font-mono text-[9px] px-1.5 py-0.5 border uppercase tracking-wide ${RISK_BG[risk] ?? RISK_BG.ADVISORY}`}
        >
          {risk}
        </span>
        <span className="font-mono text-[11px] text-text-primary font-medium">
          {action.action_type}
        </span>
        <span className="font-mono text-[9px] text-text-muted">&rarr;</span>
        <span className="font-mono text-[10px] text-text-code">
          {ridShort(action.target_rid)}
        </span>
      </div>

      {/* row 2: rationale */}
      <p className="text-[12px] font-sans text-text-secondary leading-snug">
        {action.rationale}
      </p>

      {/* row 3: metrics */}
      <div className="flex items-center gap-3 flex-wrap text-[10px] font-mono">
        <span className={confidenceColor(action.confidence * 100)}>
          {confPct}% confidence
        </span>
        <span className="text-text-secondary">
          {action.estimated_impact_mw > 0 ? "+" : ""}
          {action.estimated_impact_mw} MW
        </span>
        <span className="text-text-muted">
          {action.reversible ? "reversible" : "irreversible"}
        </span>
      </div>
    </div>
  );
}

// ── Context Summary (shown while analyzing) ──────────────────────────────────

function ContextSummary({ gs }: { gs: GridState }) {
  const alertCount = gs.active_alerts?.length ?? 0;
  const critCount =
    gs.active_alerts?.filter((a) => a.severity === "CRITICAL").length ?? 0;

  return (
    <div className="mt-3 bg-bg-secondary border border-border-subtle p-2.5 font-mono text-[10px] text-text-secondary space-y-0.5">
      <div className="text-[9px] text-text-muted uppercase tracking-wider mb-1">
        Context being sent
      </div>
      <div>
        Freq: {gs.system_frequency_hz.toFixed(3)} Hz &nbsp;|&nbsp; Gen:{" "}
        {gs.total_generation_mw.toFixed(0)} MW &nbsp;|&nbsp; Load:{" "}
        {gs.total_load_mw.toFixed(0)} MW
      </div>
      <div>
        Alerts: {alertCount} total, {critCount} critical &nbsp;|&nbsp;{" "}
        Generators: {gs.generators.length} &nbsp;|&nbsp; Lines:{" "}
        {gs.lines.length}
      </div>
    </div>
  );
}

// ── Main Panel ───────────────────────────────────────────────────────────────

export default function ReasoningPanel({ gridState }: Props) {
  const [state, setState] = useState<PanelState>("idle");
  const [result, setResult] = useState<ReasoningResult | null>(null);
  const [query, setQuery] = useState("");
  const [history, setHistory] = useState<ReasoningResult[]>([]);
  const [showHistory, setShowHistory] = useState(false);
  const [showNarrative, setShowNarrative] = useState(false);
  const lastAutoRef = useRef(0);

  // Auto-trigger awareness (for future use — currently just resets cooldown)
  useEffect(() => {
    if (!gridState) return;
    const crit = gridState.active_alerts?.filter(
      (a) => a.severity === "CRITICAL",
    );
    if (
      crit &&
      crit.length > 0 &&
      state === "idle" &&
      Date.now() - lastAutoRef.current > 5000
    ) {
      lastAutoRef.current = Date.now();
    }
  }, [gridState, state]);

  const runAnalysis = useCallback(
    async (userQuery: string) => {
      setState("analyzing");
      try {
        const r = await fetch(`${API_BASE}/reasoning`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: userQuery }),
        });
        const data: ReasoningResult = await r.json();
        setResult(data);
        setHistory((prev) => [data, ...prev].slice(0, 10));
        setState("done");
        setShowNarrative(false);
      } catch {
        setState("idle");
      }
    },
    [],
  );

  const handleAsk = () => runAnalysis(query.trim());
  const handleQuickAnalysis = () => runAnalysis("");
  const handlePreset = (text: string) => {
    setQuery(text);
    runAnalysis(text);
  };

  const reset = () => {
    setState("idle");
    setResult(null);
    setQuery("");
    setShowNarrative(false);
  };

  return (
    <div className="flex flex-col h-full">
      {/* header bar */}
      <div className="px-3 py-2 border-b border-border-subtle bg-bg-tertiary flex items-center gap-2">
        <span
          className={`w-1.5 h-1.5 rounded-full shrink-0 ${
            state === "analyzing"
              ? "bg-accent-green pulse-green"
              : state === "done"
                ? "bg-accent-green"
                : "bg-text-muted"
          }`}
        />
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          GRID Assistant
        </span>
        <span className="text-text-muted font-mono text-[9px] ml-auto">
          GPT-4o + live twin
        </span>
      </div>

      {/* scrollable content */}
      <div className="flex-1 overflow-y-auto p-3">
        {/* ══════ IDLE ══════ */}
        {state === "idle" && (
          <div className="space-y-3">
            <p className="text-[12px] font-sans text-text-secondary leading-relaxed">
              Ask a question about the live grid, or run a quick analysis.
              The assistant reads real-time telemetry and uses GPT-4o to
              assess risk and recommend actions.
            </p>

            {/* preset chips */}
            <div className="flex flex-wrap gap-1.5">
              {PRESETS.map((p) => (
                <button
                  key={p}
                  onClick={() => handlePreset(p)}
                  className="font-mono text-[10px] px-2.5 py-1 border border-border-subtle text-text-secondary hover:border-accent-blue hover:text-accent-blue transition-colors"
                >
                  {p}
                </button>
              ))}
            </div>

            {/* text input */}
            <div className="space-y-2">
              <textarea
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    handleAsk();
                  }
                }}
                placeholder="Ask the assistant anything about the grid..."
                rows={2}
                className="w-full bg-bg-secondary border border-border-subtle text-text-primary text-[12px] font-sans p-2 placeholder:text-text-muted focus:border-accent-blue focus:outline-none resize-none"
              />
              <div className="flex items-center gap-2">
                <button
                  onClick={handleAsk}
                  disabled={!query.trim()}
                  className="font-mono text-[10px] px-4 py-1.5 bg-accent-blue text-white uppercase tracking-wider hover:bg-accent-blue/80 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                >
                  Ask Assistant
                </button>
                <button
                  onClick={handleQuickAnalysis}
                  className="font-mono text-[10px] px-4 py-1.5 border border-accent-blue text-accent-blue uppercase tracking-wider hover:bg-accent-blue/10 transition-colors"
                >
                  Quick Analysis
                </button>
              </div>
            </div>
          </div>
        )}

        {/* ══════ ANALYZING ══════ */}
        {state === "analyzing" && (
          <div className="space-y-2">
            <div className="flex items-center gap-2 py-4">
              <div className="w-4 h-4 border-2 border-accent-blue border-t-transparent rounded-full animate-spin" />
              <span className="font-mono text-xs text-accent-blue">
                Analyzing grid state...
              </span>
            </div>
            {query && (
              <div className="font-sans text-[12px] text-text-secondary italic">
                &quot;{query}&quot;
              </div>
            )}
            {gridState && <ContextSummary gs={gridState} />}
          </div>
        )}

        {/* ══════ DONE ══════ */}
        {state === "done" && result && (
          <div className="space-y-3">
            {/* 1. Headline */}
            <div className="bg-bg-elevated border-l-2 border-accent-blue px-3 py-2">
              <p className="text-[14px] font-sans text-text-primary font-medium leading-snug">
                {result.operator_headline || result.response_text.slice(0, 80)}
              </p>
            </div>

            {/* 2. Answer to operator question */}
            {result.answer_to_operator && (
              <div className="bg-bg-secondary border border-border-subtle p-2.5">
                <div className="font-mono text-[9px] text-text-muted uppercase tracking-wider mb-1">
                  Your question
                </div>
                {result.user_query && (
                  <p className="text-[11px] font-sans text-text-muted italic mb-1.5">
                    &quot;{result.user_query}&quot;
                  </p>
                )}
                <p className="text-[12px] font-sans text-text-primary leading-relaxed">
                  {result.answer_to_operator}
                </p>
              </div>
            )}

            {/* 3. What we're seeing */}
            {result.what_changed && result.what_changed.length > 0 && (
              <div>
                <div className="font-mono text-[9px] text-text-muted uppercase tracking-wider mb-1">
                  What we&apos;re seeing
                </div>
                <ul className="space-y-0.5">
                  {result.what_changed.map((item, i) => (
                    <li
                      key={i}
                      className="flex items-start gap-1.5 text-[12px] font-sans text-text-secondary leading-snug"
                    >
                      <span className="text-accent-blue mt-0.5 shrink-0">&bull;</span>
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* 4. Recommended actions */}
            {result.proposed_actions.length > 0 && (
              <div>
                <div className="font-mono text-[9px] text-text-muted uppercase tracking-wider mb-1.5">
                  Recommended actions
                </div>
                <div className="space-y-1.5">
                  {result.proposed_actions.map((a, i) => (
                    <ActionCard key={i} action={a} />
                  ))}
                </div>
              </div>
            )}

            {/* 5. Risk strip */}
            <div className="flex items-center gap-6 pt-1 pb-1">
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[9px] text-text-muted uppercase">
                  Cascade risk
                </span>
                <span
                  className={`font-mono text-sm font-semibold ${cascadeColor(result.cascade_probability)}`}
                >
                  {(result.cascade_probability * 100).toFixed(0)}%
                </span>
              </div>
              <div className="flex items-center gap-1.5">
                <span className="font-mono text-[9px] text-text-muted uppercase">
                  Time window
                </span>
                <span className="font-mono text-sm font-semibold text-text-primary">
                  {result.time_horizon_seconds}s
                </span>
              </div>
            </div>

            {/* 6. Collapsible full narrative */}
            <div className="border-t border-border-subtle pt-2">
              <button
                onClick={() => setShowNarrative(!showNarrative)}
                className="font-mono text-[9px] text-text-muted uppercase tracking-wider hover:text-text-secondary transition-colors"
              >
                {showNarrative ? "▾" : "▸"} Full narrative
              </button>
              {showNarrative && (
                <div className="mt-2 bg-bg-secondary border border-border-subtle p-2.5 font-sans text-[12px] text-text-secondary leading-relaxed whitespace-pre-wrap max-h-48 overflow-y-auto">
                  {result.response_text}
                </div>
              )}
            </div>

            {/* New analysis button */}
            <button
              onClick={reset}
              className="font-mono text-[10px] px-4 py-1.5 border border-accent-blue text-accent-blue uppercase tracking-wider hover:bg-accent-blue/10 transition-colors"
            >
              New Analysis
            </button>
          </div>
        )}
      </div>

      {/* ── History drawer ── */}
      {history.length > 0 && (
        <div className="border-t border-border-subtle">
          <button
            onClick={() => setShowHistory(!showHistory)}
            className="w-full px-3 py-1.5 font-mono text-[9px] text-text-muted uppercase tracking-wider hover:bg-bg-tertiary text-left flex items-center gap-1"
          >
            <span>{showHistory ? "▾" : "▸"}</span>
            <span>History ({history.length})</span>
          </button>
          {showHistory && (
            <div className="max-h-36 overflow-y-auto px-3 pb-2 space-y-1">
              {history.map((h) => (
                <div
                  key={h.id}
                  className="font-mono text-[9px] text-text-secondary cursor-pointer hover:text-text-primary transition-colors py-0.5"
                  onClick={() => {
                    setResult(h);
                    setState("done");
                    setShowNarrative(false);
                  }}
                >
                  <span className="text-text-muted">
                    [{h.trigger_type}]{" "}
                    {new Date(h.timestamp).toLocaleTimeString()}
                  </span>{" "}
                  — {h.operator_headline || h.response_text.slice(0, 50)}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
