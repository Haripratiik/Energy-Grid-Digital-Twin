import { useCallback, useEffect, useRef, useState } from "react";
import type { AutonomousMode, GridDecision } from "../types/grid";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function useDecisions() {
  const [pending, setPending] = useState<GridDecision[]>([]);
  const [log, setLog] = useState<GridDecision[]>([]);
  const [mode, setMode] = useState<AutonomousMode>("SEMI");

  const pendingTimer = useRef<ReturnType<typeof setInterval>>();
  const logTimer = useRef<ReturnType<typeof setInterval>>();
  const modeTimer = useRef<ReturnType<typeof setInterval>>();

  const fetchPending = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/decisions/pending`);
      if (r.ok) setPending(await r.json());
    } catch {
      /* network hiccup — next poll will retry */
    }
  }, []);

  const fetchLog = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/decisions/log`);
      if (r.ok) setLog(await r.json());
    } catch {
      /* network hiccup */
    }
  }, []);

  const fetchMode = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/mode`);
      if (r.ok) {
        const data = await r.json();
        setMode(data.mode);
      }
    } catch {
      /* network hiccup */
    }
  }, []);

  useEffect(() => {
    fetchPending();
    fetchLog();
    fetchMode();

    pendingTimer.current = setInterval(fetchPending, 1000);
    logTimer.current = setInterval(fetchLog, 5000);
    modeTimer.current = setInterval(fetchMode, 10000);

    return () => {
      clearInterval(pendingTimer.current);
      clearInterval(logTimer.current);
      clearInterval(modeTimer.current);
    };
  }, [fetchPending, fetchLog, fetchMode]);

  const approve = useCallback(async (id: string) => {
    try {
      await fetch(`${API_BASE}/decisions/${id}/approve`, { method: "POST" });
      await fetchPending();
      await fetchLog();
    } catch {
      /* handled by next poll */
    }
  }, [fetchPending, fetchLog]);

  const reject = useCallback(async (id: string) => {
    try {
      await fetch(`${API_BASE}/decisions/${id}/reject`, { method: "POST" });
      await fetchPending();
      await fetchLog();
    } catch {
      /* handled by next poll */
    }
  }, [fetchPending, fetchLog]);

  const revert = useCallback(async (id: string) => {
    try {
      await fetch(`${API_BASE}/decisions/${id}/revert`, { method: "POST" });
      await fetchLog();
    } catch {
      /* handled by next poll */
    }
  }, [fetchLog]);

  const toggleMode = useCallback(async () => {
    try {
      const next: AutonomousMode = mode === "SEMI" ? "FULL_AUTO" : "SEMI";
      const r = await fetch(`${API_BASE}/mode`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: next }),
      });
      if (r.ok) {
        const data = await r.json();
        setMode(data.mode);
      }
    } catch {
      /* handled by next poll */
    }
  }, [mode]);

  return { pending, log, mode, approve, reject, revert, toggleMode };
}
