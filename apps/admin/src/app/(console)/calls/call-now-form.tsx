"use client";

import type { CallNowOptions } from "@sg/contracts";
import { useActionState, useState } from "react";

import { Badge } from "@/components/ui";
import { duration as formatDuration, usd } from "@/lib/format";

import { callNow, type CallNowState } from "./actions";

const IDLE: CallNowState = { status: "idle" };
const inputClass = "mt-1 block w-full rounded-lg border border-white/15 bg-night px-3 py-2 text-sm";

/**
 * Developer test call. Two steps (review, then confirm) so the destination and the cost estimate
 * are in front of the owner before anything dials. The request ID is fixed per attempt: a double
 * click or a retry replays the first outcome. "Start another test call" mints a new ID.
 */
export function CallNowForm({
  options,
  initialRequestId,
}: {
  options: CallNowOptions;
  initialRequestId: string;
}) {
  const [state, action, pending] = useActionState(callNow, IDLE);
  const [requestId, setRequestId] = useState(initialRequestId);
  const [confirming, setConfirming] = useState(false);
  const [agent, setAgent] = useState(options.agents.find((a) => a.configured)?.character ?? "");
  const [target, setTarget] = useState(options.targets[0] ?? "");
  const [seconds, setSeconds] = useState(Math.min(60, options.max_duration_seconds));

  const estimate =
    options.cost_per_minute_usd === null ? null : (options.cost_per_minute_usd * seconds) / 60;
  const budget = options.developer_budget;
  const remaining = budget ? budget.limit_usd - budget.committed_usd : null;
  const overBudget = remaining !== null && estimate !== null && estimate > remaining;
  const stub = options.dispatcher === "stub";
  const done = state.status === "ok";

  function startAnother() {
    setRequestId(crypto.randomUUID());
    setConfirming(false);
  }

  return (
    <form action={action} className="space-y-4">
      <input type="hidden" name="request_id" value={requestId} />
      {stub && (
        <p className="rounded-lg border border-ember/30 bg-ember/5 p-3 text-sm text-ember">
          The call dispatcher is not connected yet, so this records a test call and reserves budget
          but places no call.
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          Agent
          <select
            name="agent"
            value={agent}
            onChange={(e) => setAgent(e.target.value)}
            disabled={pending || done}
            className={inputClass}
          >
            {options.agents.map((a) => (
              <option key={a.character} value={a.character}>
                {a.character}
                {a.configured ? "" : " (no agent ID configured)"}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Agent version (optional)
          <input
            name="agent_version"
            list="agent-versions"
            maxLength={128}
            disabled={pending || done}
            className={inputClass}
          />
          <datalist id="agent-versions">
            {(options.agents.find((a) => a.character === agent)?.versions ?? []).map((v) => (
              <option key={v} value={v} />
            ))}
          </datalist>
        </label>
        <label className="text-sm">
          Destination (approved test targets only)
          <select
            name="target"
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            disabled={pending || done}
            className={inputClass}
          >
            {options.targets.map((t) => (
              <option key={t} value={t}>
                {t === "web" ? "Web call (this browser session)" : t}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          Test profile
          <select
            name="test_profile"
            defaultValue={options.test_profiles[0]}
            disabled={pending || done}
            className={inputClass}
          >
            {options.test_profiles.map((p) => (
              <option key={p} value={p}>
                {p.replaceAll("_", " ")}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm sm:col-span-2">
          Maximum duration: {formatDuration(seconds)}
          <input
            type="range"
            name="duration_seconds"
            min={options.min_duration_seconds}
            max={options.max_duration_seconds}
            step={15}
            value={seconds}
            onChange={(e) => setSeconds(Number(e.target.value))}
            disabled={pending || done}
            className="mt-2 block w-full"
          />
        </label>
      </div>

      <dl className="grid grid-cols-2 gap-2 rounded-lg bg-night/60 p-3 text-sm sm:grid-cols-4">
        <div>
          <dt className="text-xs text-foreground/50">Estimated cost</dt>
          <dd className="tabular-nums">{estimate === null ? "unpriced" : usd(estimate, 3)}</dd>
        </div>
        <div>
          <dt className="text-xs text-foreground/50">Developer budget left</dt>
          <dd className={`tabular-nums ${overBudget ? "text-bloom" : ""}`}>
            {remaining === null ? "n/a" : usd(remaining)}
          </dd>
        </div>
        <div>
          <dt className="text-xs text-foreground/50">Cooldown</dt>
          <dd>{formatDuration(options.cooldown_seconds)}</dd>
        </div>
        <div>
          <dt className="text-xs text-foreground/50">Records</dt>
          <dd>test-tagged, no garden effect</dd>
        </div>
      </dl>

      {state.status === "error" && (
        <p
          role="alert"
          className="rounded-lg border border-bloom/30 bg-bloom/5 p-3 text-sm text-bloom"
        >
          {state.message}
        </p>
      )}
      {state.status === "ok" && (
        <div role="status" className="rounded-lg border border-moss/30 bg-moss/5 p-3 text-sm">
          <p className="font-medium">
            {state.result.replayed
              ? "Already submitted: no new call was placed."
              : "Call recorded."}{" "}
            <Badge tone={state.result.state === "unknown" ? "bad" : "good"}>
              {state.result.state}
            </Badge>
          </p>
          <p className="mt-1 text-foreground/70">
            {state.result.agent} to {state.result.target} for{" "}
            {formatDuration(state.result.duration_seconds)}
            {state.result.estimated_cost_usd !== null &&
              `, about ${usd(state.result.estimated_cost_usd, 3)}`}
            . {state.result.detail}
          </p>
          <p className="mt-1 font-mono text-xs text-foreground/50">
            request {state.result.request_id}
          </p>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-3">
        {done ? (
          <button
            type="button"
            onClick={startAnother}
            className="rounded-full border border-white/15 px-5 py-2 text-sm hover:bg-white/5"
          >
            Start another test call
          </button>
        ) : confirming ? (
          <>
            <button
              type="submit"
              disabled={pending || overBudget || !agent}
              className="rounded-full bg-moss px-5 py-2 text-sm font-medium text-night disabled:opacity-50"
            >
              {pending ? "Sending..." : `Confirm: call ${target === "web" ? "via web" : target}`}
            </button>
            <button
              type="button"
              disabled={pending}
              onClick={() => setConfirming(false)}
              className="rounded-full border border-white/15 px-5 py-2 text-sm"
            >
              Back
            </button>
          </>
        ) : (
          <button
            type="button"
            onClick={() => setConfirming(true)}
            disabled={overBudget || !agent || !target}
            className="rounded-full bg-moss px-5 py-2 text-sm font-medium text-night disabled:opacity-50"
          >
            Review test call
          </button>
        )}
        {overBudget && (
          <span className="text-sm text-bloom">The estimate is above the remaining budget.</span>
        )}
      </div>
    </form>
  );
}
