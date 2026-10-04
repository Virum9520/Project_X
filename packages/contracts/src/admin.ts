/**
 * Owner-console API contracts mirroring `services/api/src/sg_api/admin/schemas.py`
 * (`GET/POST /v1/admin/*`). Hand-written until OpenAPI generation lands; keep both sides in sync.
 * Money is USD (floats rounded to micro-dollars, for display). Timestamps are ISO-8601 strings.
 */

export type CostGroupBy = "component" | "provider" | "model" | "cost_center" | "user";
export const COST_GROUP_BY: readonly CostGroupBy[] = [
  "component",
  "provider",
  "model",
  "cost_center",
  "user",
];

export const TEST_PROFILES = ["fresh_learner", "returning_learner", "interview_ready"] as const;
export type TestProfile = (typeof TEST_PROFILES)[number];

export interface BudgetStatus {
  key: string;
  limit_usd: number;
  committed_usd: number;
}

export interface Freshness {
  usage_events_at: string | null;
  cost_entries_at: string | null;
  sessions_at: string | null;
  provider_events_at: string | null;
}

export interface AdminOverview {
  generated_at: string;
  period: string;
  active_users_30d: number;
  completed_sessions_30d: number;
  spend_month_to_date_usd: number;
  projected_month_end_usd: number;
  spend_by_cost_center: Record<string, number>;
  failed_sessions_7d: number;
  failed_calls_7d: number;
  failed_provider_events: number;
  developer_budget: BudgetStatus | null;
  freshness: Freshness;
  cost_basis: string;
}

export interface AdminUserRow {
  id: string;
  email_masked: string;
  display_name: string | null;
  created_at: string;
  onboarded: boolean;
  sessions: number;
  spend_month_to_date_usd: number;
}

export interface AdminUserPage {
  items: AdminUserRow[];
  total: number;
  limit: number;
  offset: number;
}

export interface ScheduleInfo {
  id: string;
  channel: string;
  destination_masked: string | null;
  destination_verified: boolean;
  tz: string;
  local_time: string;
  days: number[];
  enabled: boolean;
  max_duration_seconds: number;
  consent_ver: string;
}

export interface ConsentInfo {
  consent_ver: string;
  phrase_verified: boolean;
  has_voice: boolean;
  created_at: string;
  revoked_at: string | null;
}

export interface UserSessionRow {
  id: string;
  character: string;
  mode: string;
  status: string;
  is_test: boolean;
  started_at: string | null;
  duration_seconds: number | null;
}

export interface AdminUserDetail {
  id: string;
  email_masked: string;
  display_name: string | null;
  timezone: string | null;
  created_at: string;
  deleted_at: string | null;
  major: string | null;
  experience_level: string | null;
  target_role: string | null;
  onboarded_at: string | null;
  plant_status_counts: Record<string, number>;
  sessions_total: number;
  open_disputes: number;
  spend_month_to_date_usd: number;
  spend_by_component: Record<string, number>;
  budget: BudgetStatus;
  schedules: ScheduleInfo[];
  voice_consent: ConsentInfo | null;
  recent_sessions: UserSessionRow[];
}

export interface CostGroup {
  key: string;
  label: string;
  usd: number;
  entries: number;
}

export interface UsageTotals {
  events: number;
  connected_seconds: number;
  input_tokens: number;
  output_tokens: number;
  /** Events that reported tokens; the rest are unknown (NULL) in the ledger, not zero. */
  token_reporting_events: number;
  sandbox_seconds: number;
}

export interface CostReport {
  start: string;
  end: string;
  group_by: CostGroupBy;
  total_usd: number;
  by_kind: Record<string, number>;
  reconciled_share: number;
  groups: CostGroup[];
  daily: { day: string; usd: number }[];
  usage: UsageTotals;
  basis: string;
}

export interface CallRow {
  occurrence_id: string;
  kind: "scheduled" | "test";
  request_id: string | null;
  user_masked: string | null;
  state: string;
  channel: string | null;
  scheduled_for: string;
  attempt_no: number | null;
  el_conversation_id: string | null;
  twilio_call_sid: string | null;
  error: string | null;
  ended_at: string | null;
}

export interface CallsReport {
  generated_at: string;
  upcoming: CallRow[];
  active: CallRow[];
  recent: CallRow[];
  state_counts_7d: Record<string, number>;
}

export interface AgentRow {
  character: string;
  agent_id: string | null;
  configured: boolean;
  sessions_30d: number;
  failed_30d: number;
  test_sessions_30d: number;
  avg_duration_seconds: number | null;
  versions: string[];
}

export interface CallNowOptions {
  agents: AgentRow[];
  targets: string[];
  test_profiles: string[];
  max_duration_seconds: number;
  min_duration_seconds: number;
  cooldown_seconds: number;
  cost_per_minute_usd: number | null;
  developer_budget: BudgetStatus | null;
  dispatcher: string;
}

export interface CallNowRequest {
  /** Client-generated idempotency key (8-64 chars of A-Z a-z 0-9 _ -). */
  request_id: string;
  agent: string;
  agent_version?: string | null;
  target: string;
  test_profile: TestProfile;
  duration_seconds: number;
}

export interface CallNowResult {
  replayed: boolean;
  occurrence_id: string;
  attempt_id: string | null;
  request_id: string;
  state: string;
  channel: string;
  target: string;
  agent: string;
  duration_seconds: number;
  estimated_cost_usd: number | null;
  el_conversation_id: string | null;
  detail: string | null;
}

export interface FailedEvent {
  id: string;
  provider: string;
  event_type: string;
  attempts: number;
  error: string | null;
  received_at: string;
}

export interface QualityReport {
  generated_at: string;
  assessments_by_status: Record<string, number>;
  judge_backlog: number;
  oldest_pending_assessment_age_s: number | null;
  open_disputes: number;
  resolved_disputes: number;
  disputes_upheld: number;
  disagreement_rate: number | null;
  provider_events_by_status: Record<string, number>;
  webhook_oldest_unprocessed_age_s: number | null;
  webhook_avg_latency_s_24h: number | null;
  failed_events: FailedEvent[];
  failed_sessions_7d: number;
  interrupted_sessions_7d: number;
}

export interface ComponentStatus {
  name: string;
  ok: boolean;
  detail: string | null;
}

export interface SystemStatus {
  generated_at: string;
  environment: string;
  git_sha: string | null;
  components: ComponentStatus[];
  configured: Record<string, boolean>;
}

export interface AuditRow {
  id: string;
  occurred_at: string;
  actor_type: string;
  actor_email: string | null;
  action: string;
  target_type: string | null;
  target_id: string | null;
  request_id: string | null;
  status_code: number | null;
  before: Record<string, unknown> | null;
  after: Record<string, unknown> | null;
}

export interface AuditPage {
  items: AuditRow[];
  next_before: string | null;
}

/** Owner assistant (C22): `POST /v1/admin/assistant/ask`, `GET /v1/admin/assistant/status`. */
export interface AssistantBasis {
  date_range: string;
  metrics: string[];
  filters: string[];
  freshness: string;
  amounts: string;
}

export interface AssistantToolTrace {
  tool: string;
  provider: string | null;
  ok: boolean;
  rows: number | null;
  truncated: boolean;
  duration_ms: number;
  error: string | null;
}

export interface AssistantTurn {
  role: "user" | "assistant";
  content: string;
}

export interface AssistantAnswer {
  request_id: string;
  answer: string;
  basis: AssistantBasis | null;
  hypotheses: string[];
  partial: boolean;
  unavailable_providers: Record<string, string>;
  tools: AssistantToolTrace[];
  warnings: string[];
  cost_usd: number;
  steps: number;
  model: string | null;
  stopped: string | null;
  generated_at: string;
}

export interface AssistantStatus {
  generated_at: string;
  model: string;
  model_configured: boolean;
  read_only: true;
  providers: Record<string, boolean>;
  tools: string[];
  limits: Record<string, number>;
  budget: BudgetStatus | null;
}
