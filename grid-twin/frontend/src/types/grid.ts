export interface BusState {
  id: number;
  voltage_angle_deg: number;
  power_generation_mw: number;
  power_load_mw: number;
  status: string;
}

export interface LineState {
  id: string;
  flow_mw: number;
  flow_pct_of_limit: number;
  status: string;
  tripped: boolean;
}

export interface GeneratorState {
  bus_id: number;
  rotor_angle_deg: number;
  rotor_speed_rad_s: number;
  mechanical_power_mw: number;
  electrical_power_mw: number;
  online: boolean;
}

export interface GridAlert {
  id: string;
  type: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  affected_asset_rids: string[];
  timestamp_sim: number;
  timestamp_wall: string;
  sensor_values: Record<string, number>;
  acknowledged: boolean;
}

export interface GridState {
  sim_time_s: number;
  wall_time: string;
  system_frequency_hz: number;
  total_generation_mw: number;
  total_load_mw: number;
  buses: BusState[];
  lines: LineState[];
  generators: GeneratorState[];
  active_alerts: GridAlert[];
  ontology_dirty: boolean;
}

export interface OntologyLink {
  target_rid: string;
  link_type: string;
}

export interface GridAsset {
  rid: string;
  object_type:
    | "GridSystem"
    | "Substation"
    | "Generator"
    | "TransmissionLine"
    | "LoadBus";
  display_name: string;
  properties: Record<string, any>;
  links: OntologyLink[];
  status: "NOMINAL" | "DEGRADED" | "OVERLOADED" | "TRIPPED" | "CRITICAL";
  last_updated: string;
}

export interface OntologyEdge {
  source_rid: string;
  target_rid: string;
  link_type: string;
}

export interface OntologyResponse {
  nodes: GridAsset[];
  edges: OntologyEdge[];
}

export interface PropagationResponse {
  affected_nodes: string[];
  affected_edges: OntologyEdge[];
  propagation_order: string[];
}

export interface ReasoningResult {
  id: string;
  triggered_by_alert_id: string | null;
  trigger_type: "AUTO_CRITICAL" | "MANUAL";
  context_snapshot: Record<string, any>;
  response_text: string;
  timestamp: string;
}

export type FaultType = "LINE_TRIP" | "GEN_DROPOUT" | "LOAD_SPIKE" | "RESTORE";

export interface FaultRequest {
  type: FaultType;
  target_rid: string;
  magnitude_mw: number;
}
