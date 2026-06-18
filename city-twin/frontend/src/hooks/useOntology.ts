import { useCallback, useEffect, useRef, useState } from "react";
import type { OntologyResponse, PropagationResponse } from "../types/grid";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "http://localhost:8000";

export function useOntology(_dirty?: boolean) {
  const [ontology, setOntology] = useState<OntologyResponse | null>(null);

  // Poll the ontology continuously so live asset statuses stay current; the
  // graph updates colours in place (no re-layout), so polling is cheap/smooth.
  useEffect(() => {
    let alive = true;
    const fetchOntology = () => {
      fetch(`${API_BASE}/ontology`)
        .then((r) => r.json())
        .then((data) => { if (alive) setOntology(data); })
        .catch(() => {});
    };
    fetchOntology();
    const id = setInterval(fetchOntology, 1000);
    return () => {
      alive = false;
      clearInterval(id);
    };
  }, []);

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
