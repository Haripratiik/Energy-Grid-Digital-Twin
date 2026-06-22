import type { VerificationResult, CorrectionAttempt } from "../types/grid";

/** "ri.city-grid.main.generator.8" → "Gen 8". */
function ridShort(rid: string): string {
  const p = rid.split(".");
  const t = p[p.length - 2] ?? "";
  const id = p[p.length - 1] ?? "";
  if (t === "transmission-line") return `Line ${id}`;
  if (t === "generator") return `Gen ${id}`;
  if (t === "load-bus") return `Bus ${id}`;
  if (t === "transformer") return `Trafo ${id}`;
  return id;
}

function Gate({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`font-mono text-[9px] ${ok ? "text-accent-green" : "text-accent-red"}`}>
      {ok ? "✓" : "✕"} {label}
    </span>
  );
}

/**
 * The physics safety-verifier verdict for an action — the heart of the
 * "AI proposes, physics disposes" story. Shows the two physics gates
 * (steady-state AC power flow + N-1 contingency security) and, when blocked,
 * exactly why.
 */
export function VerdictBadge({ v }: { v: VerificationResult }) {
  const n1Failed = v.n1_checked && !v.n1_secure;
  // The steady-state gate reads "passed" only when the verdict is safe, or when
  // the sole reason for rejection was N-1 (so steady-state genuinely passed).
  // A fail-closed / unmodellable / non-converged rejection must NOT show green.
  const steadyOk = v.safe || (n1Failed && v.converged && v.post_severity <= v.pre_severity + 1.001);
  return (
    <div
      className={`mt-2 border px-2 py-1.5 rounded-sm ${
        v.safe ? "border-accent-green/30 bg-accent-green/5" : "border-accent-red/40 bg-accent-red/10"
      }`}
    >
      <div className="flex items-center gap-2 flex-wrap">
        <span
          className={`font-mono text-[9px] px-1.5 py-0.5 uppercase tracking-wide font-semibold ${
            v.safe ? "bg-accent-green/20 text-accent-green" : "bg-accent-red/25 text-accent-red"
          }`}
        >
          {v.safe ? "✓ Physics-Verified" : "✕ Blocked by Power-Flow"}
        </span>
        <span className="font-mono text-[9px] text-text-muted">
          severity {v.pre_severity.toFixed(1)} → {v.converged ? v.post_severity.toFixed(1) : "∞"}
        </span>
      </div>
      <div className="mt-1 flex items-center gap-2.5 flex-wrap">
        <Gate ok={steadyOk} label="Steady-state AC" />
        {v.n1_checked && <Gate ok={v.n1_secure} label={`N-1 secure (${v.n1_post_insecure} exposed)`} />}
        {v.worst_voltage_pu != null && (
          <span className="font-mono text-[9px] text-text-muted">
            Vₘᵢₙ {v.worst_voltage_pu.toFixed(3)}pu
          </span>
        )}
        {v.worst_loading_pct != null && (
          <span className="font-mono text-[9px] text-text-muted">
            load {v.worst_loading_pct.toFixed(0)}%
          </span>
        )}
      </div>
      {!v.safe && (
        <div className="mt-1 font-mono text-[9px] text-accent-red/90 leading-snug">{v.reason}</div>
      )}
    </div>
  );
}

/**
 * The LLM↔physics self-correction loop: when the verifier vetoes the model's
 * first proposal, the model re-proposes against the physics feedback. Each
 * attempt + verdict is shown so the AI is visibly correcting itself.
 */
export function CorrectionTrace({ trace }: { trace?: CorrectionAttempt[] }) {
  if (!trace || trace.length < 2) return null;
  return (
    <div className="mt-2 border-l-2 border-accent-blue/40 pl-2">
      <div className="font-mono text-[8px] text-accent-blue uppercase tracking-wide mb-1">
        ⟳ Self-corrected against physics · {trace.length} attempts
      </div>
      <ol className="space-y-1">
        {trace.map((a, i) => (
          <li key={i} className="font-mono text-[9px] flex items-start gap-1.5 leading-snug">
            <span className={a.safe ? "text-accent-green" : "text-accent-red"}>
              {a.safe ? "✓" : "✕"}
            </span>
            <span className="text-text-secondary">
              <span className="text-text-primary">
                {a.action_type} {ridShort(a.target_rid)}
              </span>{" "}
              —{" "}
              <span className={a.safe ? "text-accent-green/90" : "text-accent-red/90"}>
                {a.safe ? "verified" : "vetoed"}
              </span>
              {!a.safe && (
                <span className="text-text-muted">
                  {" "}
                  (severity {a.pre_severity.toFixed(0)}→{a.post_severity.toFixed(0)})
                </span>
              )}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}
