"use client";

import { useCallback, useEffect, useState } from "react";

import { accountability } from "@/lib/accountability/client";
import {
  DURATION_OPTIONS,
  WEEKDAYS,
  describeDays,
  inQuietWindow,
  toBody,
  validateDraft,
  type ScheduleDraft,
} from "@/lib/accountability/helpers";
import {
  currentSubscription,
  disablePush,
  enablePush,
  pushSupport,
} from "@/lib/accountability/push";
import type { AccountabilityConfig, Schedule } from "@/lib/accountability/types";

const BLANK: ScheduleDraft = {
  local_time: "18:00",
  days: [1, 2, 3, 4, 5],
  tone: null,
  max_duration_seconds: 120,
  enabled: true,
  consented: false,
};

const card = "rounded-xl border border-white/10 bg-dusk/60 p-6";

const errorMessage = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong.");

export function ScheduleSettings({ defaultTz }: { defaultTz: string }) {
  const [config, setConfig] = useState<AccountabilityConfig | null>(null);
  const [schedules, setSchedules] = useState<Schedule[] | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const [c, s] = await Promise.all([accountability.config(), accountability.schedules()]);
      setConfig(c);
      setSchedules(s);
      setLoadError(null);
    } catch (e) {
      setLoadError(errorMessage(e));
    }
  }, []);

  useEffect(() => {
    // Initial fetch; `load` only sets state after the awaited requests settle.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void load();
  }, [load]);

  if (loadError) {
    return (
      <p role="alert" className="rounded-xl border border-bloom/40 bg-dusk/60 p-6 text-bloom">
        {loadError.includes("onboarding")
          ? "Finish onboarding first, then come back to set up calls."
          : `Call settings are unavailable right now (${loadError}).`}
      </p>
    );
  }
  if (!config || !schedules) return <p className="text-foreground/70">Loading…</p>;

  return (
    <>
      <PushCard config={config} />
      <SchedulesCard config={config} schedules={schedules} defaultTz={defaultTz} onChange={load} />
    </>
  );
}

function PushCard({ config }: { config: AccountabilityConfig }) {
  const [support, setSupport] = useState<ReturnType<typeof pushSupport>>("unsupported");
  const [subscribed, setSubscribed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void currentSubscription().then((sub) => {
      if (cancelled) return;
      setSupport(pushSupport());
      setSubscribed(sub !== null);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  async function toggle() {
    setBusy(true);
    setError(null);
    try {
      if (subscribed) {
        await disablePush();
        setSubscribed(false);
      } else {
        await enablePush(config.vapid_public_key);
        setSubscribed(true);
      }
      setSupport(pushSupport());
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className={card} aria-labelledby="push-h">
      <h2 id="push-h" className="font-medium">
        Ring this device
      </h2>
      <p className="mt-2 text-sm text-foreground/70">
        Allow notifications so Bhima&apos;s call reaches you even when Skill Garden is closed. If
        you skip this, the call only rings while the app is open.
      </p>
      {support === "unsupported" ? (
        <p className="mt-3 text-sm text-foreground/60">
          This browser does not support push notifications. On iPhone, add Skill Garden to your Home
          Screen first.
        </p>
      ) : !config.vapid_public_key ? (
        <p className="mt-3 text-sm text-foreground/60">
          Push is not set up on the server yet, so calls ring only while the app is open.
        </p>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <button
            onClick={toggle}
            disabled={busy || support === "denied"}
            className="rounded-xl bg-moss px-4 py-2 font-medium text-night transition hover:brightness-110 disabled:opacity-50"
          >
            {subscribed ? "Turn off notifications" : "Turn on notifications"}
          </button>
          <span className="text-sm text-foreground/60">
            {support === "denied"
              ? "Blocked in your browser settings."
              : subscribed
                ? "On for this device."
                : "Off."}
          </span>
        </div>
      )}
      {error && (
        <p role="alert" className="mt-3 text-sm text-bloom">
          {error}
        </p>
      )}
    </section>
  );
}

function SchedulesCard({
  config,
  schedules,
  defaultTz,
  onChange,
}: {
  config: AccountabilityConfig;
  schedules: Schedule[];
  defaultTz: string;
  onChange: () => Promise<void>;
}) {
  const [editing, setEditing] = useState<Schedule | "new" | null>(
    schedules.length === 0 ? "new" : null,
  );
  const [error, setError] = useState<string | null>(null);

  async function act(work: () => Promise<unknown>) {
    setError(null);
    try {
      await work();
      await onChange();
    } catch (e) {
      setError(errorMessage(e));
    }
  }

  return (
    <section className={card} aria-labelledby="sched-h">
      <div className="flex items-center justify-between gap-4">
        <h2 id="sched-h" className="font-medium">
          Call schedule
        </h2>
        {editing === null && (
          <button
            onClick={() => setEditing("new")}
            className="rounded-xl border border-white/20 px-3 py-1.5 text-sm transition hover:bg-white/5"
          >
            Add a call time
          </button>
        )}
      </div>
      <p className="mt-1 text-sm text-foreground/60">
        Quiet hours: no calls between {config.quiet_start} and {config.quiet_end}, your local time.
      </p>

      <ul className="mt-4 flex flex-col gap-3">
        {schedules.map((s) => (
          <li
            key={s.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-white/10 p-3"
          >
            <div>
              <p className="font-mono text-lg">
                {s.local_time}{" "}
                <span className="font-sans text-sm text-foreground/60">
                  {describeDays(s.days)} · {Math.round(s.max_duration_seconds / 60)} min
                  {s.tone ? ` · ${s.tone}` : ""}
                </span>
              </p>
              <p className="text-xs text-foreground/50">
                {s.tz.replaceAll("_", " ")}
                {!s.enabled && " · paused"}
              </p>
            </div>
            <div className="flex gap-2 text-sm">
              <button
                onClick={() =>
                  act(() =>
                    accountability.updateSchedule(s.id, {
                      tz: s.tz,
                      local_time: s.local_time,
                      days: s.days,
                      tone: s.tone,
                      max_duration_seconds: s.max_duration_seconds,
                      consent_version: s.consent_version,
                      enabled: !s.enabled,
                    }),
                  )
                }
                className="rounded-lg border border-white/20 px-3 py-1.5 hover:bg-white/5"
              >
                {s.enabled ? "Pause" : "Resume"}
              </button>
              <button
                onClick={() => setEditing(s)}
                className="rounded-lg border border-white/20 px-3 py-1.5 hover:bg-white/5"
              >
                Edit
              </button>
              <button
                onClick={() => act(() => accountability.deleteSchedule(s.id))}
                className="rounded-lg border border-bloom/40 px-3 py-1.5 text-bloom hover:bg-white/5"
              >
                Delete
              </button>
            </div>
          </li>
        ))}
        {schedules.length === 0 && editing === null && (
          <li className="text-sm text-foreground/60">No calls scheduled.</li>
        )}
      </ul>

      {error && editing === null && (
        <p role="alert" className="mt-3 text-sm text-bloom">
          {error}
        </p>
      )}

      {editing !== null && (
        <ScheduleForm
          key={editing === "new" ? "new" : editing.id}
          config={config}
          existing={editing === "new" ? null : editing}
          defaultTz={defaultTz}
          onCancel={schedules.length > 0 || editing !== "new" ? () => setEditing(null) : undefined}
          onSaved={async () => {
            setEditing(null);
            await onChange();
          }}
        />
      )}
    </section>
  );
}

function ScheduleForm({
  config,
  existing,
  defaultTz,
  onCancel,
  onSaved,
}: {
  config: AccountabilityConfig;
  existing: Schedule | null;
  defaultTz: string;
  onCancel?: () => void;
  onSaved: () => Promise<void>;
}) {
  const [draft, setDraft] = useState<ScheduleDraft>(
    existing
      ? {
          local_time: existing.local_time,
          days: existing.days,
          tone: existing.tone,
          max_duration_seconds: existing.max_duration_seconds,
          enabled: existing.enabled,
          // Re-confirm when the consent text version changed since they last agreed.
          consented: existing.consent_version === config.consent_version,
        }
      : BLANK,
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const tz = existing?.tz ?? defaultTz;
  const quiet = inQuietWindow(draft.local_time, config.quiet_start, config.quiet_end);

  const toggleDay = (day: number) =>
    setDraft((d) => ({
      ...d,
      days: d.days.includes(day) ? d.days.filter((x) => x !== day) : [...d.days, day],
    }));

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    const problem = validateDraft(draft);
    if (problem) return setError(problem);
    setBusy(true);
    setError(null);
    try {
      const body = toBody(draft, tz, config.consent_version);
      if (existing) await accountability.updateSchedule(existing.id, body);
      else await accountability.createSchedule(body);
      await onSaved();
    } catch (e) {
      setError(errorMessage(e));
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="mt-5 flex flex-col gap-5 border-t border-white/10 pt-5">
      <label className="flex flex-col gap-1.5 text-sm">
        <span className="text-foreground/70">Time ({tz.replaceAll("_", " ")})</span>
        <input
          type="time"
          required
          value={draft.local_time}
          onChange={(e) => setDraft({ ...draft, local_time: e.target.value })}
          className="w-40 rounded-lg border border-white/15 bg-night/60 px-3 py-2"
        />
        {quiet && (
          <span role="status" className="text-bloom">
            That is inside quiet hours ({config.quiet_start} to {config.quiet_end}), so it will be
            rejected. Pick another time.
          </span>
        )}
      </label>

      <fieldset className="text-sm">
        <legend className="mb-1.5 text-foreground/70">Days</legend>
        <div className="flex flex-wrap gap-2">
          {WEEKDAYS.map(({ day, short, long }) => (
            <label
              key={day}
              className={`cursor-pointer rounded-lg border px-3 py-1.5 has-[:focus-visible]:ring-2 ${
                draft.days.includes(day)
                  ? "border-moss bg-moss/20"
                  : "border-white/15 hover:bg-white/5"
              }`}
            >
              <input
                type="checkbox"
                className="sr-only"
                checked={draft.days.includes(day)}
                onChange={() => toggleDay(day)}
                aria-label={long}
              />
              {short}
            </label>
          ))}
        </div>
      </fieldset>

      <div className="flex flex-wrap gap-5 text-sm">
        <label className="flex flex-col gap-1.5">
          <span className="text-foreground/70">Call length (at most)</span>
          <select
            value={draft.max_duration_seconds}
            onChange={(e) => setDraft({ ...draft, max_duration_seconds: Number(e.target.value) })}
            className="rounded-lg border border-white/15 bg-night/60 px-3 py-2"
          >
            {DURATION_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s / 60} min
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1.5">
          <span className="text-foreground/70">Bhima&apos;s tone</span>
          <select
            value={draft.tone ?? ""}
            onChange={(e) =>
              setDraft({ ...draft, tone: (e.target.value || null) as ScheduleDraft["tone"] })
            }
            className="rounded-lg border border-white/15 bg-night/60 px-3 py-2"
          >
            <option value="">Default</option>
            <option value="energetic">Energetic</option>
            <option value="calm">Calm</option>
          </select>
        </label>
      </div>

      <label className="flex items-start gap-3 text-sm">
        <input
          type="checkbox"
          checked={draft.consented}
          onChange={(e) => setDraft({ ...draft, consented: e.target.checked })}
          className="mt-1 size-4 accent-[var(--moss)]"
        />
        <span>
          I agree that Skill Garden may ring me in this app at these times with an AI voice
          assistant. Calls are never placed during quiet hours and I can pause or delete them any
          time.
        </span>
      </label>

      {error && (
        <p role="alert" className="text-sm text-bloom">
          {error}
        </p>
      )}
      <div className="flex gap-3">
        <button
          type="submit"
          disabled={busy}
          className="rounded-xl bg-moss px-5 py-2 font-medium text-night transition hover:brightness-110 disabled:opacity-50"
        >
          {busy ? "Saving…" : existing ? "Save changes" : "Save schedule"}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            className="rounded-xl border border-white/20 px-4 py-2 hover:bg-white/5"
          >
            Cancel
          </button>
        )}
      </div>
    </form>
  );
}
