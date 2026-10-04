import type { SessionStartResponse } from "@sg/contracts";

/** Mirrors `services/api/src/sg_api/accountability/router.py`. */
export interface AccountabilityConfig {
  consent_version: string;
  quiet_start: string;
  quiet_end: string;
  ring_timeout_seconds: number;
  vapid_public_key: string | null;
  phone_available: boolean;
}

export interface Schedule {
  id: string;
  channel: string;
  tz: string;
  local_time: string;
  /** ISO weekdays, 1 = Monday ... 7 = Sunday. */
  days: number[];
  tone: "energetic" | "calm" | null;
  max_duration_seconds: number;
  enabled: boolean;
  consent_version: string;
}

export interface ScheduleBody {
  tz: string;
  local_time: string;
  days: number[];
  tone: "energetic" | "calm" | null;
  max_duration_seconds: number;
  consent_version: string;
  enabled: boolean;
}

export interface IncomingCall {
  attempt_id: string;
  caller: string;
  expires_at: string;
  max_duration_seconds: number;
}

export interface AcceptedCall {
  attempt_id: string;
  session: SessionStartResponse;
  max_duration_seconds: number;
  wrap_up_after_seconds: number;
  hard_stop_after_seconds: number;
  retention_concept: string | null;
}

/** The JSON the service worker receives (`WebCallChannel.dispatch`). */
export interface IncomingCallPush {
  type: "incoming_call";
  title: string;
  body: string;
  attempt_id: string;
  caller: string;
  expires_at: string;
  max_duration_seconds: number;
  url: string;
}
