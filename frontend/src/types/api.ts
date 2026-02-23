// Auto-generated from OpenAPI schema (run: uv run python scripts/generate_api_types.py)
// Do not edit manually.

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: 'firm_admin' | 'senior_engineer' | 'engineer' | 'viewer';
  firm_id: string;
  is_active: boolean;
  created_at: string;
}

export interface Firm {
  id: string;
  name: string;
  slug: string;
  created_at: string;
}

export interface ProjectListItem {
  id: string;
  name: string;
  client_name: string;
  status: 'active' | 'draft' | 'completed' | 'archived';
  jurisdiction: string;
  created_at: string;
  updated_at: string;
  last_session_at: string | null;
  num_floors: number | null;
}

export interface Project extends ProjectListItem {
  firm_id: string;
  properties: Record<string, unknown>;
  assigned_engineers: string[];
}

export interface DesignSession {
  id: string;
  project_id: string;
  status: 'pending' | 'running' | 'waiting_approval' | 'completed' | 'failed';
  created_at: string;
  completed_at: string | null;
  output_files: OutputFile[];
}

export interface OutputFile {
  name: string;
  type: 'dxf_floor_plan' | 'dxf_elevation' | 'dxf_3d' | 'dxf_mep' | 'pdf' | 'ifc' | 'dwg';
  download_url: string;
  size_bytes: number;
}

export interface JobProgress {
  session_id: string;
  step: string;
  step_index: number;
  total_steps: number;
  message: string;
  status: 'running' | 'completed' | 'failed' | 'waiting_approval';
  timestamp: string;
}

export interface ComplianceViolation {
  rule_id: string;
  severity: 'hard' | 'soft' | 'advisory';
  message: string;
  room_id?: string;
  page_ref?: string;
}

export interface ComplianceReport {
  id: string;
  session_id: string;
  violations: ComplianceViolation[];
  vastu_score: number | null;
  far_actual: number;
  far_limit: number;
  passed: boolean;
  created_at: string;
}

export interface LlmConfig {
  provider: string;
  model_name: string;
  base_url: string | null;
  api_key_set: boolean;
  temperature: number;
  max_tokens: number;
}

export interface BuildingCodeDocument {
  id: string;
  jurisdiction: string;
  title: string;
  status: 'pending' | 'extracting' | 'needs_review' | 'active';
  uploaded_at: string;
  rule_count: number;
}

export interface ExtractedRule {
  id: string;
  rule_id: string;
  category: string;
  value: number | string;
  unit: string | null;
  description: string;
  page_ref: string | null;
  confidence: number;
  status: 'pending' | 'approved' | 'rejected';
}

export interface PlotInfo {
  area_sqm: number;
  width_m: number;
  depth_m: number;
  facing: string;
  is_rectangular: boolean;
  north_direction_deg: number;
  road_width_m: number | null;
  polygon: Array<{ x: number; y: number }>;
  extraction_confidence: number;
}

// Floor plan types for SVG renderer
export interface FloorPlan {
  floor: number;
  floor_height: number;
  buildable_zone: { x: number; y: number; width: number; depth: number };
  rooms: RoomLayout[];
  wall_segments: WallSegment[];
  columns: ColumnPosition[];
  mep_network: MEPNetwork | null;
}

export interface RoomLayout {
  room_id: string;
  room_type: string;
  name: string;
  floor: number;
  bounds: { x: number; y: number; width: number; depth: number };
  doors: Door[];
  windows: Window[];
}

export interface WallSegment {
  start: { x: number; y: number };
  end: { x: number; y: number };
  thickness: number;
  is_load_bearing: boolean;
  is_external: boolean;
}

export interface ColumnPosition {
  x: number;
  y: number;
  width: number;
  depth: number;
}

export interface Door {
  wall_face: 'north' | 'south' | 'east' | 'west';
  position_along_wall: number;
  width: number;
  swing: 'left' | 'right';
  is_main_entrance: boolean;
}

export interface Window {
  wall_face: 'north' | 'south' | 'east' | 'west';
  position_along_wall: number;
  width: number;
  height: number;
  sill_height: number;
}

export interface MEPNetwork {
  conduit_runs: ConduitRun[];
  plumbing_stacks: PlumbingStack[];
  panels: ElectricalPanel[];
  total_electrical_load_kva: number;
  total_pipe_run_m: number;
}

export interface ConduitRun {
  run_id: string;
  circuit_name: string;
  path: Array<{ x: number; y: number; floor: number }>;
  wire_gauge_mm2: number;
  conduit_dia_mm: number;
  load_kva: number;
}

export interface PlumbingStack {
  stack_id: string;
  wet_rooms: string[];
  cold_pipe_path: Array<{ x: number; y: number; floor: number }>;
  hot_pipe_path: Array<{ x: number; y: number; floor: number }>;
  pipe_dia_mm: number;
  floors_served: number[];
}

export interface ElectricalPanel {
  panel_id: string;
  location: { x: number; y: number; floor: number };
  num_circuits: number;
  load_kva: number;
  phase: '1-phase' | '3-phase';
}

export interface ElevationView {
  direction: 'front' | 'rear' | 'left' | 'right';
  width_m: number;
  height_m: number;
  floor_levels: number[];
  openings: ElevationOpening[];
  parapet_height_m: number;
}

export interface ElevationOpening {
  type: 'window' | 'door';
  x_m: number;
  width_m: number;
  bottom_m: number;
  height_m: number;
}

export interface BuildingOutline3D {
  vertices: Array<{ x: number; y: number; z: number }>;
  edges: Array<[number, number]>;
  roof_edge_indices: number[];
}
