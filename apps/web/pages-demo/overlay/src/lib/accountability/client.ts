import { inQuietWindow } from "@/lib/accountability/helpers";
import { newId, readRecords, updateRecords } from "@/lib/practice/store";

import type {
  AcceptedCall,
  AccountabilityConfig,
  IncomingCall,
  Schedule,
  ScheduleBody,
} from "@/lib/accountability/types";

/**
 * Static-site version of the accountability client: Bhima's schedule is kept in this browser
 * (`localStorage`), with the same rules the API enforces (quiet hours, consent version). Calls
 * ring on the schedule page while it is open; there are no push notifications without a server.
 */

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** Mirrors `sg_core.accountability.dispatcher.CallPolicy` defaults. */
const CONFIG: AccountabilityConfig = {
  consent_version: "bhima-calls-v1",
  quiet_start: "21:30",
  quiet_end: "08:00",
  ring_timeout_seconds: 45,
  vapid_public_key: null,
  phone_available: false,
};

function validate(body: ScheduleBody) {
  if (!/^([01]\d|2[0-3]):[0-5]\d$/.test(body.local_time))
    throw new ApiError("Choose a valid time.", 422);
  if (!body.days.length || body.days.some((d) => d < 1 || d > 7))
    throw new ApiError("Choose at least one day.", 422);
  if (body.consent_version !== CONFIG.consent_version)
    throw new ApiError("Confirm the current call consent first.", 409);
  if (inQuietWindow(body.local_time, CONFIG.quiet_start, CONFIG.quiet_end))
    throw new ApiError(
      `That time is inside quiet hours (${CONFIG.quiet_start} to ${CONFIG.quiet_end}).`,
      422,
    );
}

const toSchedule = (id: string, body: ScheduleBody): Schedule => ({
  id,
  channel: "web",
  tz: body.tz,
  local_time: body.local_time,
  days: [...new Set(body.days)].sort((a, b) => a - b),
  tone: body.tone,
  max_duration_seconds: body.max_duration_seconds,
  enabled: body.enabled,
  consent_version: body.consent_version,
});

function save(change: (schedules: Schedule[]) => Schedule[]) {
  const ok = updateRecords((r) => ({ ...r, schedules: change(r.schedules) }));
  if (!ok) throw new ApiError("This browser did not let the schedule be saved.", 507);
}

const unsupported = (): never => {
  throw new ApiError("Calls ring on the schedule page while it is open.", 501);
};

export const accountability = {
  config: async () => CONFIG,
  schedules: async () => readRecords().schedules,
  createSchedule: async (body: ScheduleBody) => {
    validate(body);
    const schedule = toSchedule(newId("sch"), body);
    save((all) => [...all, schedule]);
    return schedule;
  },
  updateSchedule: async (id: string, body: ScheduleBody) => {
    validate(body);
    const schedule = toSchedule(id, body);
    if (!readRecords().schedules.some((s) => s.id === id))
      throw new ApiError("That call time no longer exists.", 404);
    save((all) => all.map((s) => (s.id === id ? schedule : s)));
    return schedule;
  },
  deleteSchedule: async (id: string) => {
    save((all) => all.filter((s) => s.id !== id));
  },
  subscribePush: async (_sub: PushSubscriptionJSON): Promise<void> => unsupported(),
  revokePush: async (_endpoint: string): Promise<void> => unsupported(),
  incoming: async (): Promise<{ call: IncomingCall | null }> => ({ call: null }),
  accept: async (_id: string): Promise<AcceptedCall> => unsupported(),
  decline: async (_id: string): Promise<void> => undefined,
  end: async (_id: string, _durationSeconds?: number): Promise<void> => undefined,
};

export const ACCOUNTABILITY_CONFIG = CONFIG;
