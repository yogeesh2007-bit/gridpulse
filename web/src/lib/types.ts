// Shapes of the JSON the FastAPI backend returns (only the fields the UI uses).

export type Role = "driver" | "operator";
export type PriorityClass = "urgent" | "normal" | "flexible";
export type ReservationStatus = "queued" | "active" | "done" | "cancelled";

export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
}

export interface AuthResponse {
  user: User;
  access_token: string;
  token_type: string;
  expires_in: number;
}

export interface StationState {
  available_ports: number;
  queue_count: number;
  current_load_w: number;
  site_power_limit_w: number;
  lat: number;
  lng: number;
}

/** What a driver may see about a station. */
export interface PublicStation {
  id: number;
  code: string;
  name: string;
  kind: "physical" | "simulated";
  lat: number;
  lon: number;
  lng: number;
  ports: number;
  max_kw_per_port: number;
  site_limit_kw: number;
  is_online: boolean;
  available_ports: number;
  queue_count: number;
  current_load_w: number;
  site_power_limit_w: number;
  utilization_pct: number;
  over_limit: boolean;
  ev_load_kw: number;
  current_load_kw: number;
  headroom_kw: number;
  ports_busy: number;
  state: StationState;
}

export interface ScoreBreakdown {
  travel_time: number;
  predicted_wait: number;
  charging_time: number;
  load_penalty: number;
  urgency_bonus: number;
  final_score: number;
  urgency: number;
  immediacy: number;
  deadline_factor: number;
  projected_load_pct: number;
}

export interface RankingEntry {
  rank: number;
  station_id: number;
  code: string;
  name: string;
  kind: string;
  feasible: boolean;
  rejection_reason: string | null;
  final_score: number | null;
  travel_time_min: number;
  predicted_wait_min: number;
  charge_time_min: number;
  total_time_min: number | null;
  ready_at: string | null;
  charge_kw: number;
  distance_km: number;
  deadline_ok: boolean | null;
  score_breakdown: ScoreBreakdown | null;
  station_state: StationState;
}

export interface Explanation {
  text: string;
  source: "rules" | "llm";
  model?: string | null;
}

export interface RoutingInfo {
  fallback_used: boolean;
  estimated: boolean;
  sources: string[];
  confidence: "high" | "reduced";
  note: string | null;
}

export interface Recommendation {
  request_id: number;
  generated_at: string;
  driver: {
    name: string;
    soc_current: number;
    soc_target: number;
    deadline_minutes: number;
    urgency: number;
    priority_class: PriorityClass;
  };
  chosen_station: { id: number; code: string; name: string; kind: string; lat: number; lng: number } | null;
  ranking: RankingEntry[];
  predicted_wait_min: number | null;
  travel_time_min: number | null;
  charge_time_min: number | null;
  score_breakdown: ScoreBreakdown | null;
  formula: string;
  explanation: Explanation;
  warnings: string[];
  routing: RoutingInfo;
  comparison_with_nearest: {
    nearest_station_name: string;
    minutes_saved: number | null;
    extra_travel_min: number;
  } | null;
}

export interface ExplanationResult {
  request_id: number;
  text: string;
  source: "rules" | "llm";
  model: string | null;
  fallback_reason: string | null;
  latency_ms: number;
}

export interface DriverRequestInput {
  driver_name?: string;
  lat: number;
  lng: number;
  soc: number;
  target_soc: number;
  deadline: number; // minutes from now
  battery_kwh?: number;
  max_charge_kw?: number;
  location_source: "gps" | "manual";
  location_accuracy_m?: number | null;
}

export interface Reservation {
  id: number;
  request_id: number | null;
  station_id: number;
  station_code: string;
  station_name: string;
  driver_name: string;
  priority_class: PriorityClass;
  urgency: number;
  soc_arrival: number;
  soc_target: number;
  allocated_kw: number;
  status: ReservationStatus;
  queue_position: number | null;
  arrival_at: string;
  planned_start_at: string;
  planned_end_at: string;
  minutes_to_start: number;
  minutes_to_end: number;
  created_at: string;
}

export interface LatestRequest {
  request: {
    id: number;
    lat: number;
    lon: number;
    soc_current: number;
    soc_target: number;
    deadline_minutes: number;
    battery_kwh: number;
    max_charge_kw: number;
    priority_class: PriorityClass;
    urgency: number;
    created_at: string;
  } | null;
  recommendation: Recommendation | null;
  reservation: Reservation | null;
}

export interface LiveEta {
  station_id: number;
  station_code: string;
  station_name: string;
  distance_km: number;
  travel_min: number;
  route_source: string;
  route_fallback: boolean;
}

export interface LocationUpdateResult {
  request_id: number;
  etas: LiveEta[];
  updates: number;
  updated_at: string;
  routing_fallback_used: boolean;
}

export interface GeoResult {
  name: string;
  short_name: string;
  source: "nominatim" | "cache" | "fallback";
  cached: boolean;
}

export interface DriverSnapshot {
  reservations: Reservation[];
  stations: PublicStation[];
}

// ---- operator ------------------------------------------------------------------------------------------
export interface QueueItem {
  reservation_id: number;
  position: number;
  driver_name: string;
  priority_class: PriorityClass;
  urgency: number;
  kw: number;
  arrival_at: string;
  planned_start_at: string;
  starts_in_min: number;
}

export interface ActiveItem {
  reservation_id: number;
  driver_name: string;
  priority_class: PriorityClass;
  kw: number;
  port_index: number | null;
  soc_target: number;
  ends_at: string;
  remaining_min: number;
}

export interface ControlView {
  station_id: number;
  station_code: string;
  station_name: string;
  device_id: string | null;
  command: "NORMAL" | "REDUCE_LOAD" | "PRIORITIZE_URGENT" | "PAUSE_FLEX";
  reason: string;
  power_fraction: number;
  duty_pct: number;
  seq: number;
  valid_for_s: number;
  command_generated_at: string;
  updated_at: string;
  source: "hardware" | "simulated";
  confirmation: "simulated" | "hardware-pending" | "hardware-confirmed";
  hardware_confirmed: boolean;
  device_mode: "real" | "simulated" | null;
  freshness: "live" | "stale" | "offline" | "none";
  hardware_mode: string | null;
  telemetry_age_s: number | null;
  ack_status: string;
  dry_run: boolean | null;
  sensor_status: string | null;
  local_override: boolean;
  caveats: string[];
  fallback_reason: string | null;
}

export interface DeviceView {
  device_id: string;
  device_mode: "real" | "simulated";
  registered: boolean;
  placeholder: boolean;
  station_code: string | null;
  freshness: "live" | "stale" | "offline";
  telemetry_age_s: number | null;
  last_telemetry_at: string | null;
  last_seen_at: string | null;
  telemetry_source: string | null;
  hardware_confirmed: boolean;
  confirmation: string;
  ack_status: string;
  dry_run: boolean;
  sensor_status: string;
  output_physical: boolean;
  local_override: boolean;
  button_count: number;
  firmware_version: string | null;
  current_command: { command: string; seq: number } | null;
  last_command_sent: { command: string; seq: number; at: string } | null;
  last_ack: { seq: number; status: string; detail: string | null; at: string } | null;
  caveats: string[];
  fallback_reason: string | null;
}

export interface Telemetry {
  device_id: string;
  voltage: number;
  current: number;
  power: number;
  temperature: number | null;
  mode: string | null;
  note: string | null;
  source: string;
  sensor_status: string;
  received_at: string;
  age_s: number;
}

export interface OperatorStation extends PublicStation {
  queue: QueueItem[];
  active: ActiveItem[];
  queue_length: number;
  base_load_kw: number;
  is_chosen_for_latest: boolean;
  control: ControlView | null;
  device: DeviceView | null;
  telemetry: Telemetry | null;
}

export interface HardwareSummary {
  real_live: number;
  simulated_live: number;
  stale: number;
  offline: number;
  placeholder: number;
  total: number;
  mode: "real" | "simulated" | "software";
}

export interface ControlEvent {
  id: number;
  ts: string;
  station_code: string;
  command: string;
  previous: string | null;
  reason: string;
  power_fraction: number;
}

export interface LiveDriver {
  request_id: number;
  driver_name: string;
  priority_class: PriorityClass | null;
  lat: number;
  lon: number;
  accuracy_m: number | null;
  age_s: number;
  is_live: boolean;
  updates: number;
}

export interface TimelineItem {
  reservation_id: number;
  station_id: number;
  driver_name: string;
  priority_class: PriorityClass;
  status: ReservationStatus;
  allocated_kw: number;
  start_min: number;
  end_min: number;
}

export interface OperatorState {
  now: string;
  totals: { stations: number; stations_online: number; active_sessions: number; queued: number; ev_load_kw: number };
  stations: OperatorStation[];
  reservations: Reservation[];
  recent_finished: Reservation[];
  latest_recommendation: {
    request_id: number;
    generated_at: string;
    driver: Recommendation["driver"];
    chosen_station: Recommendation["chosen_station"];
    ranking: RankingEntry[];
    explanation: Explanation;
    warnings: string[];
    formula: string;
  } | null;
  devices: DeviceView[];
  hardware_summary: HardwareSummary;
  control_events: ControlEvent[];
  live_drivers: LiveDriver[];
  timeline: { horizon_min: number; items: TimelineItem[] };
  system: {
    routing: { mode: string; osrm_available: boolean; cooldown_s: number; last_error: string | null };
    openrouter_configured: boolean;
    openrouter_model: string;
  };
}

export interface OperatorControl {
  commands: string[];
  stations: ControlView[];
  devices: DeviceView[];
  hardware_summary: HardwareSummary;
  events: ControlEvent[];
}
