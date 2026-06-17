export interface BusState {
  id: number;
  voltage_magnitude_pu: number;
  voltage_kv: number;
  voltage_angle_deg: number;
  power_generation_mw: number;
  power_load_mw: number;
  status: string;
}

export interface LineState {
  id: string;
  voltage_kv: number;
  flow_mw: number;
  flow_pct_of_limit: number;
  status: string;
  tripped: boolean;
}

export interface TransformerState {
  id: string;
  from_bus: number;
  to_bus: number;
  tap_ratio: number;
  loading_pct: number;
  temperature_c: number;
  status: string;
}

export interface GeneratorState {
  bus_id: number;
  gen_type: "THERMAL" | "HYDRO" | "SOLAR" | "WIND" | "NUCLEAR" | "GAS";
  capacity_mw: number;
  rotor_angle_deg: number;
  rotor_speed_rad_s: number;
  mechanical_power_mw: number;
  electrical_power_mw: number;
  online: boolean;
  extra: Record<string, unknown>;
}

export interface GridAlert {
  id: string;
  type: string;
  severity: "INFO" | "WARNING" | "CRITICAL";
  affected_asset_rids: string[];
  timestamp_sim: number;
  timestamp_wall: string;
  sensor_values: Record<string, number>;
  summary?: string;
  acknowledged: boolean;
}

/** Compact N-1 summary merged into the SSE stream (full report at /contingencies). */
export interface ContingencySummary {
  base_secure: boolean;
  n_insecure: number;
  n_screened: number;
  worst: {
    contingency_id: string;
    label: string;
    outcome: string;
    severity: number;
  } | null;
}

export interface GridState {
  sim_time_s: number;
  wall_time: string;
  system_frequency_hz: number;
  total_generation_mw: number;
  total_load_mw: number;
  total_loss_mw: number;
  buses: BusState[];
  lines: LineState[];
  generators: GeneratorState[];
  transformers: TransformerState[];
  active_alerts: GridAlert[];
  ontology_dirty: boolean;
  contingency?: ContingencySummary | null;
}

// --- N-1 contingency analysis (GET /contingencies) ---

export type ContingencyOutcome =
  | "SECURE"
  | "THERMAL_OVERLOAD"
  | "VOLTAGE_VIOLATION"
  | "COLLAPSE";

export interface ContingencyViolation {
  asset_rid: string;
  kind: string;
  value: number;
  detail: string;
}

export interface ContingencyResult {
  contingency_id: string;
  kind: "LINE" | "TRANSFORMER" | "GENERATOR";
  label: string;
  outcome: ContingencyOutcome;
  severity: number;
  converged: boolean;
  n_violations: number;
  worst_voltage_pu?: number | null;
  worst_loading_pct?: number | null;
  violations: ContingencyViolation[];
}

export interface ContingencyReport {
  base_secure: boolean;
  base_converged: boolean;
  n_screened: number;
  n_ac_verified: number;
  n_insecure: number;
  worst: ContingencyResult | null;
  results: ContingencyResult[];
}

// --- Digital twin (GET /twin/run) ---

export interface TwinStep {
  t: number;
  angle_rmse: number;
  speed_rmse: number;
  nis: number;
  anomaly_active: boolean;
}

export interface TwinSummary {
  n_steps: number;
  n_measured: number;
  n_states: number;
  converged_angle_rmse: number;
  converged_speed_rmse: number;
  initial_angle_rmse: number;
  nis_baseline_mean: number;
  nis_anomaly_peak: number;
  anomaly_detected: boolean;
}

export interface TwinRunResponse {
  summary: TwinSummary;
  anomaly_step: number | null;
  dt_s: number;
  steps: TwinStep[];
}

// --- Performance benchmark (GET /perf/lodf) ---

export interface LodfBenchRow {
  case: string;
  n_bus: number;
  n_branch: number;
  build_ms: number;
  lodf_screen_ms: number;
  bruteforce_ms: number;
  bruteforce_projected: boolean;
  speedup: number;
  contingencies_per_s: number;
  max_error_pu: number;
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
    | "Transformer"
    | "LoadBus";
  display_name: string;
  properties: Record<string, unknown>;
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

export interface ProposedAction {
  action_type: string;
  target_rid: string;
  parameters: Record<string, unknown>;
  rationale: string;
  confidence: number;
  estimated_impact_mw: number;
  reversible: boolean;
  risk_level?: RiskLevel;
}

export interface ReasoningResult {
  id: string;
  triggered_by_alert_id: string | null;
  trigger_type: "AUTO_CRITICAL" | "MANUAL";
  user_query: string | null;
  context_snapshot: Record<string, unknown>;
  operator_headline: string;
  answer_to_operator: string | null;
  what_changed: string[];
  response_text: string;
  proposed_actions: ProposedAction[];
  cascade_probability: number;
  time_horizon_seconds: number;
  timestamp: string;
}

export type FaultType =
  | "LINE_TRIP"
  | "TRAFO_TRIP"
  | "GEN_DROPOUT"
  | "LOAD_SPIKE"
  | "GEN_SETPOINT"
  | "RESTORE";

export interface FaultRequest {
  type: FaultType;
  target_rid: string;
  magnitude_mw: number;
}

export type AutonomousMode = "SEMI" | "FULL_AUTO";

export type RiskLevel = "ADVISORY" | "CONTROLLED" | "CRITICAL" | "EMERGENCY";

export interface ChatThread {
  id: string;
  title: string;
  created_at: string;
  message_count: number;
}

export interface ChatMessageStructured {
  what_changed?: string[];
  proposed_actions?: ProposedAction[];
  cascade_probability?: number;
  time_horizon_seconds?: number;
}

export interface ChatMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
  structured?: ChatMessageStructured | null;
  timestamp: string;
}

/** Matches backend `decisions.models.GridDecision` JSON. */
export interface GridDecision {
  id: string;
  risk_level: RiskLevel;
  action: ProposedAction;
  triggered_by_alert_id?: string | null;
  status: "PENDING" | "APPROVED" | "REJECTED" | "EXECUTED" | "REVERTED" | "EXPIRED";
  /** When the decision was created (backend field name). */
  timestamp: string;
  expires_at?: string | null;
  executed_by?: string | null;
  pre_state_snapshot?: Record<string, unknown>;
  post_state_snapshot?: Record<string, unknown> | null;
  outcome_delta: Record<string, number> | null;
}
