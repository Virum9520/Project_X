import { describe, expect, it } from "vitest";

import {
  describeDays,
  formatClock,
  inQuietWindow,
  isAllowedRoute,
  secondsUntil,
  toBody,
  urlBase64ToUint8Array,
  validateDraft,
} from "./helpers";

const ID = "123e4567-e89b-12d3-a456-426614174000";

describe("proxy allowlist", () => {
  it("allows the learner routes with their methods only", () => {
    expect(isAllowedRoute("config", "GET")).toBe(true);
    expect(isAllowedRoute("config", "POST")).toBe(false);
    expect(isAllowedRoute(`schedules/${ID}`, "DELETE")).toBe(true);
    expect(isAllowedRoute(`calls/${ID}/accept`, "POST")).toBe(true);
    expect(isAllowedRoute("calls/incoming", "GET")).toBe(true);
  });
  it("rejects anything else", () => {
    expect(isAllowedRoute("schedules/../../admin", "GET")).toBe(false);
    expect(isAllowedRoute(`calls/${ID}/accept/extra`, "POST")).toBe(false);
    expect(isAllowedRoute("admin/users", "GET")).toBe(false);
  });
});

describe("helpers", () => {
  it("decodes a URL-safe VAPID key", () => {
    expect(Array.from(urlBase64ToUint8Array("AQID"))).toEqual([1, 2, 3]);
    expect(Array.from(urlBase64ToUint8Array("-_8"))).toEqual([251, 255]);
  });
  it("counts down without going negative", () => {
    const now = Date.parse("2026-01-01T00:00:00Z");
    expect(secondsUntil("2026-01-01T00:00:10.200Z", now)).toBe(11);
    expect(secondsUntil("2025-12-31T23:59:00Z", now)).toBe(0);
    expect(secondsUntil("nope", now)).toBe(0);
    expect(formatClock(125)).toBe("2:05");
  });
  it("describes days", () => {
    expect(describeDays([1, 2, 3, 4, 5])).toBe("Weekdays");
    expect(describeDays([7, 6])).toBe("Weekends");
    expect(describeDays([1, 3])).toBe("Mon, Wed");
    expect(describeDays([1, 2, 3, 4, 5, 6, 7])).toBe("Every day");
  });
  it("detects the quiet window across midnight", () => {
    expect(inQuietWindow("22:00", "21:30", "08:00")).toBe(true);
    expect(inQuietWindow("07:59", "21:30", "08:00")).toBe(true);
    expect(inQuietWindow("08:00", "21:30", "08:00")).toBe(false);
    expect(inQuietWindow("12:00", "21:30", "08:00")).toBe(false);
  });
  it("validates and builds the schedule body", () => {
    const draft = {
      local_time: "18:30",
      days: [3, 1, 3],
      tone: null,
      max_duration_seconds: 120,
      enabled: true,
      consented: true,
    };
    expect(validateDraft(draft)).toBeNull();
    expect(validateDraft({ ...draft, days: [] })).toMatch(/day/);
    expect(validateDraft({ ...draft, consented: false })).toMatch(/agree/);
    expect(validateDraft({ ...draft, local_time: "" })).toMatch(/time/);
    expect(toBody(draft, "America/Detroit", "bhima-calls-v1")).toMatchObject({
      days: [1, 3],
      tz: "America/Detroit",
      consent_version: "bhima-calls-v1",
    });
  });
});
