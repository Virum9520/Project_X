import type {
  AcceptedCall,
  AccountabilityConfig,
  IncomingCall,
  Schedule,
  ScheduleBody,
} from "./types";

const BASE = "/api/accountability";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function call<T>(path: string, method = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`${BASE}/${path}`, {
    method,
    cache: "no-store",
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (response.status === 204) return undefined as T;
  const payload = (await response.json().catch(() => ({}))) as {
    detail?: string | { message?: string };
  };
  if (!response.ok) {
    const detail = payload.detail;
    const message =
      typeof detail === "string"
        ? detail
        : (detail?.message ?? `Request failed (${response.status})`);
    throw new ApiError(message, response.status);
  }
  return payload as T;
}

export const accountability = {
  config: () => call<AccountabilityConfig>("config"),
  schedules: () => call<Schedule[]>("schedules"),
  createSchedule: (body: ScheduleBody) => call<Schedule>("schedules", "POST", body),
  updateSchedule: (id: string, body: ScheduleBody) =>
    call<Schedule>(`schedules/${id}`, "PUT", body),
  deleteSchedule: (id: string) => call<void>(`schedules/${id}`, "DELETE"),
  subscribePush: (sub: PushSubscriptionJSON) => call<void>("push-subscriptions", "POST", sub),
  revokePush: (endpoint: string) => call<void>("push-subscriptions/revoke", "POST", { endpoint }),
  incoming: () => call<{ call: IncomingCall | null }>("calls/incoming"),
  accept: (id: string) => call<AcceptedCall>(`calls/${id}/accept`, "POST", {}),
  decline: (id: string) => call<void>(`calls/${id}/decline`, "POST", {}),
  end: (id: string, durationSeconds?: number) =>
    call<void>(`calls/${id}/end`, "POST", { duration_seconds: durationSeconds ?? null }),
};
