"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { accountability } from "@/lib/accountability/client";
import type { IncomingCall } from "@/lib/accountability/types";

const POLL_MS = 5000;

/**
 * Fallback for browsers without push (or with it blocked): while the app is open, poll for a
 * ringing call and show a banner that opens the call screen. Safe to mount anywhere in the
 * learner app; it renders nothing until a call is ringing.
 */
export function IncomingCallListener() {
  const [call, setCall] = useState<IncomingCall | null>(null);

  useEffect(() => {
    let cancelled = false;
    let announced: string | null = null;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      if (document.visibilityState === "visible") {
        try {
          const result = await accountability.incoming();
          if (!cancelled) {
            const next = result.call;
            if (next && next.attempt_id !== announced) {
              announced = next.attempt_id;
              window.dispatchEvent(
                new CustomEvent("sg:incoming-call", { detail: { attemptId: next.attempt_id } }),
              );
            }
            if (!next) announced = null;
            setCall(next);
          }
        } catch {
          if (!cancelled) setCall(null);
        }
      }
      if (!cancelled) timer = setTimeout(poll, POLL_MS);
    };
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, []);

  if (!call) return null;
  return (
    <div
      role="alert"
      className="glass fixed inset-x-4 top-24 z-50 mx-auto flex max-w-md items-center justify-between gap-4 rounded-2xl p-4 shadow-xl"
    >
      <p>
        <span className="font-medium">Incoming call from {call.caller}</span>
      </p>
      <Link
        href={{ pathname: `/call/${call.attempt_id}` }}
        className="rounded-xl bg-moss px-4 py-2 font-medium text-night"
      >
        Open
      </Link>
    </div>
  );
}
