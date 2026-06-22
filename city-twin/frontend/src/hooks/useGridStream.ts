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
  const reconnectRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const closedRef = useRef(false);

  const connect = useCallback(() => {
    if (closedRef.current) return;
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
      if (closedRef.current) return;
      setConnectionStatus("disconnected");
      const delay = retryRef.current;
      retryRef.current = Math.min(delay * 2, 16000);
      reconnectRef.current = setTimeout(connect, delay);
    };
  }, []);

  useEffect(() => {
    closedRef.current = false;
    connect();
    return () => {
      closedRef.current = true;
      if (reconnectRef.current) clearTimeout(reconnectRef.current);
      eventSourceRef.current?.close();
    };
  }, [connect]);

  return { gridState, connectionStatus };
}

export { API_BASE };
