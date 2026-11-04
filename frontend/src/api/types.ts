export type Severity = "RED" | "AMBER" | "GREEN" | "INFO";
export type Role = "PATIENT" | "CAREGIVER" | "NURSE" | "SURGEON" | "ADMIN";

export interface User {
  id: string;
  email: string;
  full_name: string;
  role: Role;
  title?: string | null;
  permissions: string[];
  patient_id?: string | null;
}

export interface Phase {
  key: string;
  label: string;
  start_day: number | null;
  end_day: number | null;
  description: string;
}

export interface Episode {
  id: string;
  procedure_type: string;
  procedure_name: string;
  surgery_date: string;
  discharge_date: string;
  hospital: string;
  surgeon: string | null;
  recovery_day: number;
  phase: Phase;
}

export interface PatientSummary {
  id: string;
  mrn: string;
  full_name: string;
  first_name: string;
  last_name: string;
  date_of_birth: string;
  current_risk: Severity;
  phone?: string;
  episode: Episode | null;
}

export interface Task {
  id: string;
  category: string;
  title: string;
  detail: string;
  completed: boolean;
}

export interface MedSlot {
  medication_id: string;
  name: string;
  dose_text: string;
  time: string;
  scheduled_for: string | null;
  status: string;
  recorded: boolean;
  instructions: string;
  as_needed: boolean;
}

export interface Appointment {
  id: string;
  appointment_type: string;
  provider_name: string;
  location: string;
  scheduled_at: string;
  status: string;
  transportation_status: string;
  transportation_note?: string | null;
  transport?: TransportRequest | null;
}

export interface TransportRequest {
  id: string;
  status: "REQUESTED" | "SCHEDULED" | "COMPLETED" | "CANCELLED";
  kind: "HOSPITAL_PICKUP" | "HELP_FINDING_RIDE";
  return_trip: boolean;
  mobility_needs: string[];
  companion: boolean;
  pickup_address: string | null;
  requested_pickup_at: string | null;
  patient_note: string | null;
  mode: string | null;
  mode_label: string | null;
  vendor: string | null;
  pickup_at: string | null;
  vehicle: string | null;
  driver_name: string | null;
  contact_phone: string | null;
  confirmation_code: string | null;
  created_at: string;
}

export interface SurveyState {
  instrument: string;
  title: string;
  timepoint: string;
  label: string;
  window: [number, number];
  state: "UPCOMING" | "DUE" | "COMPLETED" | "MISSED";
  raw_score: number | null;
  max_score: number | null;
  completed_at: string | null;
}

export interface Message {
  id: string;
  sender_type: string;
  sender_name: string;
  content: string;
  safety_level?: Severity | null;
  intent?: string | null;
  answered_from_content?: boolean | null;
  citations: Citation[];
  actions: string[];
  created_at: string;
  read_at?: string | null;
}

export interface Citation {
  title: string;
  section: string;
  version?: number;
  authority?: string;
  doc_type?: string;
  approved_by?: string | null;
  score?: number;
  excerpt?: string;
}

export interface Dashboard {
  patient: PatientSummary;
  episode: Episode | null;
  recovery_day: number;
  phase: Phase;
  phases: Phase[];
  progress_pct: number;
  plan_approved: boolean;
  tasks: Task[];
  checkin: { completed_today: boolean; risk_level: Severity | null; submitted_at: string | null; total_completed: number };
  medications: MedSlot[];
  next_appointment: Appointment | null;
  care_team_messages: Message[];
  unread_messages: number;
  escalation_status: { severity: Severity; status: string; message: string; since: string } | null;
  current_risk: Severity;
  mood: { date: string; mood: string; score: number }[];
  surveys_due: SurveyState[];
}

export interface Alert {
  id: string;
  patient_id: string;
  patient_name: string;
  patient_mrn?: string;
  severity: Severity;
  category: string;
  source: string;
  rule_id: string;
  trigger: string;
  reason?: string;
  evidence: unknown[];
  status: string;
  required_response_minutes: number;
  due_at: string;
  assigned_team: string;
  created_at: string;
  acknowledged_at?: string | null;
  first_contact_at?: string | null;
  resolved_at?: string | null;
  resolution?: string | null;
  sla: { state: "ON_TRACK" | "DUE_SOON" | "BREACHED" | "MET"; minutes_remaining: number | null };
  last_checkin_at?: string | null;
  action?: string;
}

export interface ChatResponse {
  answer: string;
  safety_level: Severity;
  intent: string;
  answered_from_content: boolean;
  emergency: boolean;
  citations: Citation[];
  retrieval: Record<string, unknown>;
  actions: string[];
  alert_id: string | null;
  model: string | null;
  provider: string | null;
  prompt_version: string;
  latency_ms: number;
  flags: string[];
  disclaimer: string;
}

export interface CheckinQuestion {
  key: string;
  text: string;
  answer_type: "SCALE" | "CHOICE" | "MULTI" | "NUMBER" | "BOOLEAN" | "TEXT";
  options: { value: string; label: string }[];
  min_value: number | null;
  max_value: number | null;
  unit: string | null;
  required: boolean;
  help_text: string | null;
}

export interface TimelineEvent {
  timestamp: string;
  type: string;
  title: string;
  detail: string;
  severity: Severity | null;
  actor: string | null;
}
