import type { ScheduleBody } from "./types";

export const WEEKDAYS = [
  { day: 1, short: "Mon", long: "Monday" },
  { day: 2, short: "Tue", long: "Tuesday" },
  { day: 3, short: "Wed", long: "Wednesday" },
  { day: 4, short: "Thu", long: "Thursday" },
  { day: 5, short: "Fri", long: "Friday" },
  { day: 6, short: "Sat", long: "Saturday" },
  { day: 7, short: "Sun", long: "Sunday" },
] as const;

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
export const isUuid = (value: string): boolean => UUID.test(value);

/** Browser-proxy allowlist: only the learner accountability routes, with the methods each allows. */
const ROUTES: { pattern: RegExp; methods: readonly string[] }[] = [
  { pattern: /^config$/, methods: ["GET"] },
  { pattern: /^schedules$/, methods: ["GET", "POST"] },
  { pattern: /^schedules\/[0-9a-f-]{36}$/i, methods: ["PUT", "DELETE"] },
  { pattern: /^push-subscriptions$/, methods: ["POST"] },
  { pattern: /^push-subscriptions\/revoke$/, methods: ["POST"] },
  { pattern: /^commitments$/, methods: ["GET"] },
  { pattern: /^calls\/incoming$/, methods: ["GET"] },
  { pattern: /^calls\/[0-9a-f-]{36}\/(accept|decline|end)$/i, methods: ["POST"] },
];

export function isAllowedRoute(route: string, method: string): boolean {
  return ROUTES.some((r) => r.pattern.test(route) && r.methods.includes(method));
}

/** VAPID public keys travel as URL-safe base64; `pushManager.subscribe` wants the raw bytes. */
export function urlBase64ToUint8Array(value: string): Uint8Array<ArrayBuffer> {
  const padded = value + "=".repeat((4 - (value.length % 4)) % 4);
  const raw = atob(padded.replaceAll("-", "+").replaceAll("_", "/"));
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i += 1) out[i] = raw.charCodeAt(i);
  return out;
}

/** Whole seconds left until `iso`, never negative. */
export function secondsUntil(iso: string, now: number): number {
  const target = Date.parse(iso);
  if (Number.isNaN(target)) return 0;
  return Math.max(0, Math.ceil((target - now) / 1000));
}

export function formatClock(totalSeconds: number): string {
  const s = Math.max(0, Math.floor(totalSeconds));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

export function describeDays(days: readonly number[]): string {
  const sorted = [...new Set(days)].sort((a, b) => a - b);
  if (sorted.length === 7) return "Every day";
  if (sorted.join() === "1,2,3,4,5") return "Weekdays";
  if (sorted.join() === "6,7") return "Weekends";
  return sorted.map((d) => WEEKDAYS[d - 1]?.short ?? "?").join(", ");
}

export const DURATION_OPTIONS = [60, 90, 120, 180] as const;

export interface ScheduleDraft {
  local_time: string;
  days: number[];
  tone: "energetic" | "calm" | null;
  max_duration_seconds: number;
  enabled: boolean;
  consented: boolean;
}

/** Returns an error message, or null when the draft can be saved. */
export function validateDraft(draft: ScheduleDraft): string | null {
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(draft.local_time)) return "Choose a time for the call.";
  if (draft.days.length === 0) return "Choose at least one day.";
  if (!draft.consented) return "Confirm you agree to receive these calls.";
  return null;
}

export function toBody(draft: ScheduleDraft, tz: string, consentVersion: string): ScheduleBody {
  return {
    tz,
    local_time: draft.local_time,
    days: [...new Set(draft.days)].sort((a, b) => a - b),
    tone: draft.tone,
    max_duration_seconds: draft.max_duration_seconds,
    consent_version: consentVersion,
    enabled: draft.enabled,
  };
}

/** True when `localTime` falls inside the quiet window (which may wrap midnight). */
export function inQuietWindow(localTime: string, start: string, end: string): boolean {
  if (start === end) return false;
  return start < end
    ? localTime >= start && localTime < end
    : localTime >= start || localTime < end;
}
