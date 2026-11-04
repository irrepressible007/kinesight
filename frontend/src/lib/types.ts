export type StepStatus =
  | "PASS"
  | "FAIL_MISSING"
  | "FAIL_COUNT_SHORTFALL"
  | "FAIL_SHORT_DURATION"
  | "FAIL_ORDER";

export interface SopStep {
  step_number: number;
  description: string;
  actor_object: string;
  target_object: string;
  min_contact_sec: number;
  required_contacts: number;
}

export interface CompiledSop {
  sop_title: string;
  sam_prompts: string[];
  steps: SopStep[];
}

export interface ContactInterval {
  start_sec: number;
  end_sec: number;
  duration_sec: number;
  mean_overlap_px: number;
  location: [number, number] | null;
  meets_min_duration: boolean;
}

export interface StepResult {
  event_id: string;
  step_number: number;
  description: string;
  actor: string;
  target: string;
  min_contact_sec: number;
  contact_intervals: ContactInterval[];
  contacts_detected: number;
  contacts_required: number;
  status: StepStatus;
}

export interface Telemetry {
  video_id: string;
  fps_analyzed: number;
  total_frames: number;
  total_duration_sec: number;
  frame_width: number;
  frame_height: number;
  detected_interactions: StepResult[];
}

export interface Defect {
  step_number: number;
  status: StepStatus;
  severity: "CRITICAL" | "MAJOR" | "MINOR";
  timestamp_sec: number;
  keyframe_paths: string[];
  root_cause_summary: string;
  corrective_action: string;
  corrective_diagram_url: string | null;
  auditor_confirmed: boolean | null;
  auditor_confidence: number | null;
}

export interface AuditVerdict {
  overall_status: "PASS" | "FAIL" | "REVIEW";
  cycle_time_sec: number;
  compliance_score: number;
  defects: Defect[];
}

export interface JobResult {
  job_id: string;
  video_url: string;
  tracks_url: string;
  sop: CompiledSop;
  telemetry: Telemetry;
  verdict: AuditVerdict;
  timings_ms: Record<string, number>;
  cached: boolean;
}

export interface JobStatus {
  job_id: string;
  status: "queued" | "running" | "done" | "failed";
  stage: string | null;
  error: string | null;
  result: JobResult | null;
}

export interface TrackFrame {
  poly: number[][];
  c: [number, number] | null;
}

export interface Tracks {
  fps: number;
  width: number;
  height: number;
  total_frames: number;
  labels: string[];
  tracks: Record<string, TrackFrame[]>;
  speed: Record<string, (number | null)[]>;
  contact: Record<string, number[]>;
  stationary_speed: number;
}

export interface Preset {
  id: string;
  title: string;
  subtitle: string;
  sop_text: string;
  sop: CompiledSop;
  video_url: string;
  source: { credit: string; url: string };
}
