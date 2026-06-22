import { useEffect, useRef, useState } from "react";
import { useChat } from "../hooks/useChat";
import MarkdownLite from "./MarkdownLite";
import type {
  GridState,
  ChatMessage,
  ProposedAction,
  RiskLevel,
} from "../types/grid";

interface Props {
  gridState: GridState | null;
}

const PRESETS = [
  "Summarize grid health",
  "How do I use this app?",
  "What should I worry about?",
  "Explain the frequency trend",
] as const;

const RISK_BG: Record<string, string> = {
  ADVISORY: "bg-accent-blue/15 text-accent-blue border-accent-blue/30",
  CONTROLLED: "bg-accent-yellow/15 text-accent-yellow border-accent-yellow/30",
  CRITICAL: "bg-accent-red/15 text-accent-red border-accent-red/30",
  EMERGENCY: "bg-accent-red text-white border-accent-red",
};

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

function ActionCard({ action }: { action: ProposedAction }) {
  const risk: RiskLevel = action.risk_level ?? "ADVISORY";
  const confPct = (action.confidence * 100).toFixed(0);

  return (
    <div className="bg-bg-primary/50 border border-border-subtle p-2 space-y-1">
      <div className="flex items-center gap-1.5 flex-wrap">
        <span
          className={`font-mono text-[8px] px-1 py-0.5 border uppercase tracking-wide ${RISK_BG[risk] ?? RISK_BG.ADVISORY}`}
        >
          {risk}
        </span>
        <span className="font-mono text-[10px] text-text-primary font-medium">
          {action.action_type}
        </span>
        <span className="font-mono text-[8px] text-text-muted">&rarr;</span>
        <span className="font-mono text-[9px] text-text-code">
          {ridShort(action.target_rid)}
        </span>
      </div>
      <p className="text-[11px] font-sans text-text-secondary leading-snug">
        {action.rationale}
      </p>
      <div className="flex items-center gap-2 flex-wrap text-[9px] font-mono">
        <span className={confidenceColor(action.confidence * 100)}>
          {confPct}%
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

function AssistantMessage({ msg }: { msg: ChatMessage }) {
  const s = msg.structured;
  const actions = (s?.proposed_actions ?? []) as ProposedAction[];
  const whatChanged = (s?.what_changed ?? []) as string[];
  const cascade = s?.cascade_probability ?? 0;
  const horizon = s?.time_horizon_seconds ?? 0;

  return (
    <div className="space-y-2 max-w-full">
      <div className="text-[12px] font-sans text-text-secondary">
        <MarkdownLite text={msg.content} />
      </div>

      {whatChanged.length > 0 && (
        <div className="bg-bg-secondary border border-border-subtle p-2">
          <div className="font-mono text-[8px] text-text-muted uppercase tracking-wider mb-1">
            Key observations
          </div>
          <ul className="space-y-0.5">
            {whatChanged.map((item, i) => (
              <li
                key={i}
                className="flex items-start gap-1 text-[11px] font-sans text-text-secondary"
              >
                <span className="text-accent-blue shrink-0">&bull;</span>
                {item}
              </li>
            ))}
          </ul>
        </div>
      )}

      {actions.length > 0 && (
        <div>
          <div className="font-mono text-[8px] text-text-muted uppercase tracking-wider mb-1">
            Recommended actions
          </div>
          <div className="space-y-1">
            {actions.map((a, i) => (
              <ActionCard key={i} action={a} />
            ))}
          </div>
        </div>
      )}

      {cascade > 0 && (
        <div className="flex items-center gap-4 text-[10px] font-mono">
          <span className="text-text-muted">Cascade:</span>
          <span className={cascadeColor(cascade)}>
            {(cascade * 100).toFixed(0)}%
          </span>
          {horizon > 0 && (
            <>
              <span className="text-text-muted">Window:</span>
              <span className="text-text-primary">{horizon}s</span>
            </>
          )}
        </div>
      )}
    </div>
  );
}

export default function ChatPanel({ gridState }: Props) {
  const {
    threads,
    activeThreadId,
    messages,
    loading,
    createThread,
    selectThread,
    deleteThread,
    sendMessage,
  } = useChat();

  const [input, setInput] = useState("");
  const [showThreads, setShowThreads] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [messages, loading]);

  const handleSend = () => {
    const text = input.trim();
    if (!text || loading) return;
    setInput("");
    sendMessage(text);
  };

  const handlePreset = (text: string) => {
    if (loading) return;
    setInput("");
    sendMessage(text);
  };

  const activeThread = threads.find((t) => t.id === activeThreadId);

  return (
    <div className="flex flex-col h-full">
      {/* header */}
      <div className="px-3 py-2 border-b border-border-subtle bg-bg-tertiary flex items-center gap-2">
        <button
          onClick={() => setShowThreads(!showThreads)}
          className="font-mono text-[9px] text-text-muted hover:text-text-secondary transition-colors"
          title="Toggle threads"
        >
          {showThreads ? "▾" : "▸"}
        </button>
        <span className="w-1.5 h-1.5 rounded-full bg-accent-green shrink-0" />
        <span className="font-mono text-[10px] text-text-muted uppercase tracking-widest">
          GRID Assistant
        </span>
        <span className="text-text-muted font-mono text-[9px] ml-auto">
          GPT-4o
        </span>
        <button
          onClick={createThread}
          className="font-mono text-[9px] px-2 py-0.5 border border-border-subtle text-text-secondary hover:border-accent-blue hover:text-accent-blue transition-colors"
          title="New chat"
        >
          + New
        </button>
      </div>

      {/* thread list (collapsible) */}
      {showThreads && (
        <div className="border-b border-border-subtle bg-bg-secondary max-h-32 overflow-y-auto">
          {threads.length === 0 && (
            <div className="px-3 py-2 font-mono text-[9px] text-text-muted">
              No conversations yet
            </div>
          )}
          {threads.map((t) => (
            <div
              key={t.id}
              className={`flex items-center px-3 py-1.5 cursor-pointer transition-colors ${
                t.id === activeThreadId
                  ? "bg-accent-blue/10 border-l-2 border-accent-blue"
                  : "hover:bg-bg-elevated border-l-2 border-transparent"
              }`}
              onClick={() => {
                selectThread(t.id);
                setShowThreads(false);
              }}
            >
              <div className="flex-1 min-w-0">
                <div className="font-mono text-[10px] text-text-primary truncate">
                  {t.title}
                </div>
                <div className="font-mono text-[8px] text-text-muted">
                  {t.message_count} msgs
                </div>
              </div>
              <button
                onClick={(e) => {
                  e.stopPropagation();
                  deleteThread(t.id);
                }}
                className="font-mono text-[9px] text-text-muted hover:text-accent-red transition-colors ml-2 shrink-0"
                title="Delete"
              >
                &times;
              </button>
            </div>
          ))}
        </div>
      )}

      {/* messages area */}
      <div ref={scrollRef} className="flex-1 overflow-y-auto p-3 space-y-3">
        {messages.length === 0 && !loading && (
          <div className="space-y-3">
            <p className="text-[12px] font-sans text-text-secondary leading-relaxed">
              Ask anything about the live grid, get recommendations, or learn
              how the system works. Your conversation is remembered within each
              chat thread.
            </p>
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
            {gridState && (
              <div className="bg-bg-secondary border border-border-subtle p-2 font-mono text-[10px] text-text-muted space-y-0.5">
                <div className="text-[8px] uppercase tracking-wider mb-1">
                  Live status
                </div>
                <div>
                  Freq: {gridState.system_frequency_hz.toFixed(3)} Hz |
                  Gen: {gridState.total_generation_mw.toFixed(0)} MW |
                  Load: {gridState.total_load_mw.toFixed(0)} MW
                </div>
              </div>
            )}
          </div>
        )}

        {messages.map((msg) => (
          <div
            key={msg.id}
            className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[90%] ${
                msg.role === "user"
                  ? "bg-accent-blue/15 border border-accent-blue/20 px-3 py-2"
                  : "bg-bg-secondary border border-border-subtle px-3 py-2"
              }`}
            >
              {msg.role === "user" ? (
                <div className="text-[12px] font-sans text-text-primary">
                  {msg.content}
                </div>
              ) : (
                <AssistantMessage msg={msg} />
              )}
              <div className="font-mono text-[8px] text-text-muted mt-1.5">
                {(() => {
                  try {
                    const d = new Date(msg.timestamp);
                    return isNaN(d.getTime()) ? "" : d.toLocaleTimeString();
                  } catch { return ""; }
                })()}
              </div>
            </div>
          </div>
        ))}

        {loading && (
          <div className="flex justify-start">
            <div className="bg-bg-secondary border border-border-subtle px-3 py-2 flex items-center gap-2">
              <div className="w-3 h-3 border-2 border-accent-blue border-t-transparent rounded-full animate-spin" />
              <span className="font-mono text-[10px] text-accent-blue">
                Thinking...
              </span>
            </div>
          </div>
        )}
      </div>

      {/* input area */}
      <div className="border-t border-border-subtle bg-bg-tertiary p-2 space-y-2">
        {messages.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {PRESETS.map((p) => (
              <button
                key={p}
                onClick={() => handlePreset(p)}
                disabled={loading}
                className="font-mono text-[9px] px-2 py-0.5 border border-border-subtle text-text-muted hover:border-accent-blue hover:text-accent-blue transition-colors disabled:opacity-40"
              >
                {p}
              </button>
            ))}
          </div>
        )}
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                handleSend();
              }
            }}
            placeholder={
              activeThread
                ? "Ask the assistant..."
                : "Start typing to begin a new chat..."
            }
            rows={1}
            disabled={loading}
            className="flex-1 bg-bg-secondary border border-border-subtle text-text-primary text-[12px] font-sans px-2 py-1.5 placeholder:text-text-muted focus:border-accent-blue focus:outline-none resize-none disabled:opacity-40 min-h-[32px] max-h-[80px]"
            style={{ height: "auto" }}
            onInput={(e) => {
              const t = e.currentTarget;
              t.style.height = "auto";
              t.style.height = Math.min(t.scrollHeight, 80) + "px";
            }}
          />
          <button
            onClick={handleSend}
            disabled={!input.trim() || loading}
            className="font-mono text-[10px] px-3 py-1.5 bg-accent-blue text-white uppercase tracking-wider hover:bg-accent-blue/80 transition-colors disabled:opacity-40 disabled:cursor-not-allowed shrink-0"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  );
}
