import { atlantaPreset, legacyPreset } from "./presets";
import type { CityMapPreset } from "./presets";

const STORAGE_KEY = "city-twin:active-preset";
const CUSTOM_KEY = "city-twin:custom-preset";

const BUILT_IN: CityMapPreset[] = [atlantaPreset, legacyPreset];

export function listPresets(): CityMapPreset[] {
  const custom = loadCustomPreset();
  return custom ? [...BUILT_IN, custom] : [...BUILT_IN];
}

export function getActivePresetId(): string {
  return localStorage.getItem(STORAGE_KEY) ?? "atlanta";
}

export function setActivePresetId(id: string): void {
  localStorage.setItem(STORAGE_KEY, id);
}

export function getActivePreset(): CityMapPreset {
  const id = getActivePresetId();
  if (id === "custom") {
    const custom = loadCustomPreset();
    if (custom) return custom;
  }
  return BUILT_IN.find((p) => p.id === id) ?? atlantaPreset;
}

export function saveCustomPreset(preset: CityMapPreset): void {
  localStorage.setItem(CUSTOM_KEY, JSON.stringify(preset));
  setActivePresetId("custom");
}

export function loadCustomPreset(): CityMapPreset | null {
  const raw = localStorage.getItem(CUSTOM_KEY);
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw);
    if (validatePreset(parsed)) return parsed;
  } catch { /* invalid JSON */ }
  return null;
}

export function clearCustomPreset(): void {
  localStorage.removeItem(CUSTOM_KEY);
  if (getActivePresetId() === "custom") {
    setActivePresetId("atlanta");
  }
}

export function validatePreset(obj: unknown): obj is CityMapPreset {
  if (!obj || typeof obj !== "object") return false;
  const p = obj as Record<string, unknown>;
  if (typeof p.id !== "string" || typeof p.name !== "string") return false;
  if (!Array.isArray(p.buses) || p.buses.length !== 80) return false;
  const ids = new Set<number>();
  for (const b of p.buses) {
    if (
      typeof b !== "object" || !b ||
      typeof (b as any).id !== "number" ||
      typeof (b as any).x !== "number" ||
      typeof (b as any).y !== "number" ||
      typeof (b as any).district !== "string"
    ) return false;
    const id = (b as any).id as number;
    if (id < 1 || id > 80 || ids.has(id)) return false;
    ids.add(id);
  }
  if (ids.size !== 80) return false;
  return true;
}
