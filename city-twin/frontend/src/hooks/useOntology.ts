import { useCallback, useEffect, useRef, useState } from "react";
import type { OntologyResponse, PropagationResponse } from "../types/grid";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function useOntology(dirty: boolean) {
  const [ontology, setOntology] = useState<OntologyResponse | null>(null);
  const lastFetch = useRef(0);

  useEffect(() => {
    if (!dirty && ontology) return;
    const now = Date.now();
    if (now - lastFetch.current < 500) return;
    lastFetch.current = now;

    fetch(`${API_BASE}/ontology`)
      .then((r) => r.json())
      .then(setOntology)
      .catch(() => {});
  }, [dirty, ontology]);

  const fetchPropagation = useCallback(
    async (alertId: string): Promise<PropagationResponse | null> => {
      try {
        const r = await fetch(
          `${API_BASE}/ontology/propagation?alert_id=${alertId}`
        );
        return await r.json();
      } catch {
        return null;
      }
    },
    []
  );

  return { ontology, fetchPropagation };
}
