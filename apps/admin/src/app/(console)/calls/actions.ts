"use server";

import { TEST_PROFILES, type CallNowResult, type TestProfile } from "@sg/contracts";
import { refresh } from "next/cache";

import { apiPost } from "@/lib/api";
import { requireOwner } from "@/lib/owner";

export type CallNowState =
  | { status: "idle" }
  | { status: "ok"; result: CallNowResult }
  | { status: "error"; message: string };

/**
 * Server action behind "Call now". It re-checks the owner session, then posts to the API, which
 * checks the `calls.trigger` capability, the approved target, the cooldown and the budget, and
 * audits the request. The request ID comes from the form so a repeat submit replays, never re-dials.
 */
export async function callNow(_previous: CallNowState, form: FormData): Promise<CallNowState> {
  await requireOwner();
  const profile = String(form.get("test_profile") ?? "");
  if (!(TEST_PROFILES as readonly string[]).includes(profile)) {
    return { status: "error", message: "Pick a test profile." };
  }
  const duration = Number(form.get("duration_seconds"));
  if (!Number.isInteger(duration)) return { status: "error", message: "Enter a duration." };
  const version = String(form.get("agent_version") ?? "").trim();

  const result = await apiPost<CallNowResult>("/v1/admin/calls/now", {
    request_id: String(form.get("request_id") ?? ""),
    agent: String(form.get("agent") ?? ""),
    agent_version: version || null,
    target: String(form.get("target") ?? ""),
    test_profile: profile as TestProfile,
    duration_seconds: duration,
  });
  if (!result.ok) {
    return { status: "error", message: result.detail };
  }
  refresh();
  return { status: "ok", result: result.data };
}
