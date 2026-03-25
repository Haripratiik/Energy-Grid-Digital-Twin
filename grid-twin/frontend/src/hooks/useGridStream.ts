import { useCallback, useEffect, useRef, useState } from "react";
import type { GridState } from "../types/grid";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export type ConnectionStatus = "connecting" | "connected" | "disconnected";

export function useGridStream() {
  const [gridState, setGridState] = useState<GridState | null>(null);
  const [connectionStatus, setConnectionStatus] =
    useState<ConnectionStatus>("connecting");
  const retryRef = useRef(1000);
  const eventSourceRef = useRef<EventSource | null>(null);

  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setConnectionStatus("connecting");
    const es = new EventSource(`${API_BASE}/stream`);
    eventSourceRef.current = es;

    es.onopen = () => {
      setConnectionStatus("connected");
      retryRef.current = 1000;
    };

    es.onmessage = (event) => {
      try {
        const state: GridState = JSON.parse(event.data);
        setGridState(state);
      } catch {
        // ignore parse errors on keepalive
      }
    };

    es.onerror = () => {
      es.close();
      setConnectionStatus("disconnected");
      const delay = retryRef.current;
      retryRef.current = Math.min(delay * 2, 16000);
      setTimeout(connect, delay);
    };
  }, []);

  useEffect(() => {
    connect();
    return () => {
      eventSourceRef.current?.close();
    };
  }, [connect]);

  return { gridState, connectionStatus };
}

export { API_BASE };
