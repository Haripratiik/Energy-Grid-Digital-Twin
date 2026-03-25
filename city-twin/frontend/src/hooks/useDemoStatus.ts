import { useCallback, useEffect, useRef, useState } from "react";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export interface DemoStatus {
  active: boolean;
  phase: string | null;
}

export function useDemoStatus() {
  const [status, setStatus] = useState<DemoStatus>({ active: false, phase: null });
  const timer = useRef<ReturnType<typeof setInterval>>();

  const fetch_ = useCallback(async () => {
    try {
      const r = await fetch(`${API_BASE}/demo/status`);
      if (r.ok) setStatus(await r.json());
    } catch { /* next poll */ }
  }, []);

  useEffect(() => {
    fetch_();
    timer.current = setInterval(fetch_, 3000);
    return () => clearInterval(timer.current);
  }, [fetch_]);

  return status;
}
