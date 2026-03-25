import { useState, useCallback, useMemo } from "react";
import type { CityMapPreset } from "../data/presets";
import {
  getActivePreset,
  getActivePresetId,
  setActivePresetId,
  saveCustomPreset,
  clearCustomPreset,
  listPresets,
} from "../data/cityMapPresets";

export interface UseCityMapPreset {
  preset: CityMapPreset;
  presetId: string;
  allPresets: CityMapPreset[];
  switchPreset: (id: string) => void;
  applyCustom: (p: CityMapPreset) => void;
  resetCustom: () => void;
  /** Bump this counter to force CityMapView to rebuild its static SVG layers. */
  revision: number;
}

export function useCityMapPreset(): UseCityMapPreset {
  const [revision, setRevision] = useState(0);
  const [presetId, setPresetIdState] = useState(getActivePresetId);
  const preset = useMemo(() => getActivePreset(), [presetId, revision]);
  const allPresets = useMemo(() => listPresets(), [presetId, revision]);

  const switchPreset = useCallback((id: string) => {
    setActivePresetId(id);
    setPresetIdState(id);
    setRevision((r) => r + 1);
  }, []);

  const applyCustom = useCallback((p: CityMapPreset) => {
    saveCustomPreset(p);
    setPresetIdState("custom");
    setRevision((r) => r + 1);
  }, []);

  const resetCustom = useCallback(() => {
    clearCustomPreset();
    setPresetIdState(getActivePresetId());
    setRevision((r) => r + 1);
  }, []);

  return { preset, presetId, allPresets, switchPreset, applyCustom, resetCustom, revision };
}
