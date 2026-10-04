"use client";

import "@/lib/voice/quiet-livekit";
import { ConversationProvider, useConversation } from "@elevenlabs/react";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { useSoundscape } from "@/components/soundscape/soundscape-provider";
import { accountability, ApiError } from "@/lib/accountability/client";
import { formatClock, secondsUntil } from "@/lib/accountability/helpers";
import type { AcceptedCall, IncomingCall } from "@/lib/accountability/types";

type Phase =
  "checking" | "ringing" | "connecting" | "live" | "ended" | "missed" | "declined" | "error";

const RING_POLL_MS = 3000;

export function IncomingCallScreen({ attemptId }: { attemptId: string }) {
  return (
    <ConversationProvider>
      <Screen attemptId={attemptId} />
    </ConversationProvider>
  );
}

function Screen({ attemptId }: { attemptId: string }) {
  const sound = useSoundscape();
  const [phase, setPhase] = useState<Phase>("checking");
  const [call, setCall] = useState<IncomingCall | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [ringLeft, setRingLeft] = useState(0);
  const [elapsed, setElapsed] = useState(0);
  const accepted = useRef<AcceptedCall | null>(null);
  const startedAt = useRef(0);
  const ended = useRef(false);
  const phaseRef = useRef<Phase>("checking");
  const wrapUpSent = useRef(false);

  const go = useCallback((next: Phase) => {
    phaseRef.current = next;
    setPhase(next);
  }, []);

  const finish = useCallback(
    (reason: "ended" | "error") => {
      if (ended.current) return;
      ended.current = true;
      const seconds = startedAt.current ? Math.round((Date.now() - startedAt.current) / 1000) : 0;
      void accountability.end(attemptId, seconds).catch(() => undefined);
      go(reason);
    },
    [attemptId, go],
  );

  const conversation = useConversation({
    onDisconnect: () => {
      if (phaseRef.current === "live") finish("ended");
    },
    onError: (message) => {
      setError(message || "The voice connection failed.");
      if (phaseRef.current === "live" || phaseRef.current === "connecting") finish("error");
    },
  });

  // Is this call actually ringing? The poll doubles as the fallback when push never arrived.
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    const check = async () => {
      if (phaseRef.current !== "checking" && phaseRef.current !== "ringing") return;
      try {
        const { call: current } = await accountability.incoming();
        if (cancelled) return;
        if (current && current.attempt_id === attemptId) {
          setCall(current);
          if (phaseRef.current === "checking") go("ringing");
        } else {
          go("missed");
          return;
        }
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : "Could not check for the call.");
        go("error");
        return;
      }
      timer = setTimeout(check, RING_POLL_MS);
    };
    void check();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [attemptId, go]);

  // Ring countdown, plus the soundscape ring tone (silent unless the learner enabled sound).
  useEffect(() => {
    if (phase !== "ringing" || !call) return;
    const tick = () => {
      const left = secondsUntil(call.expires_at, Date.now());
      setRingLeft(left);
      if (left <= 0) go("missed");
    };
    tick();
    window.dispatchEvent(new CustomEvent("sg:incoming-call", { detail: { attemptId } }));
    const countdown = setInterval(tick, 500);
    sound?.play({ type: "ring" });
    const ring = setInterval(() => sound?.play({ type: "ring" }), 3000);
    return () => {
      clearInterval(countdown);
      clearInterval(ring);
    };
  }, [phase, call, go, sound, attemptId]);

  // In-call clock: ask Bhima to wrap up, then hard-stop at the server's cap.
  useEffect(() => {
    if (phase !== "live") return;
    const timer = setInterval(() => {
      const plan = accepted.current;
      if (!plan) return;
      const seconds = Math.round((Date.now() - startedAt.current) / 1000);
      setElapsed(seconds);
      if (seconds >= plan.wrap_up_after_seconds && !wrapUpSent.current) {
        wrapUpSent.current = true;
        try {
          conversation.sendUserMessage(
            "[The call is almost out of time. Please wrap up in a sentence or two and say goodbye.]",
          );
        } catch {
          // The hard stop below still ends the call.
        }
      }
      if (seconds >= plan.hard_stop_after_seconds) {
        conversation.endSession();
        finish("ended");
      }
    }, 500);
    return () => clearInterval(timer);
  }, [phase, conversation, finish]);

  async function answer() {
    go("connecting");
    setError(null);
    try {
      const plan = await accountability.accept(attemptId);
      accepted.current = plan;
      const { session } = plan;
      conversation.startSession({
        conversationToken: session.conversation_token,
        connectionType: "webrtc",
        dynamicVariables: session.dynamic_variables,
        onConnect: () => {
          startedAt.current = Date.now();
          go("live");
        },
      });
    } catch (e) {
      if (e instanceof ApiError && (e.status === 409 || e.status === 410 || e.status === 404)) {
        go("missed");
        return;
      }
      setError(
        e instanceof ApiError
          ? e.message
          : "Could not start the call. Check microphone access and try again.",
      );
      // If the API already accepted, tell it the call did not connect; otherwise it just rings out.
      if (accepted.current) finish("error");
      else go("error");
    }
  }

  async function decline() {
    go("declined");
    await accountability.decline(attemptId).catch(() => undefined);
  }

  function hangUp() {
    conversation.endSession();
    finish("ended");
  }

  return (
    <main className="mx-auto flex min-h-[100svh] w-full max-w-md flex-1 flex-col items-center justify-center gap-8 px-6 py-24 text-center">
      <Avatar pulsing={phase === "ringing" || (phase === "live" && conversation.isSpeaking)} />
      <div aria-live="polite" className="flex flex-col items-center gap-2">
        {phase === "checking" && <p className="text-foreground/70">Checking for your call…</p>}
        {phase === "ringing" && (
          <>
            <p className="text-sm uppercase tracking-[0.3em] text-glow">Incoming call</p>
            <h1 className="text-3xl font-semibold">Incoming call from Bhima</h1>
            <p className="text-foreground/70">
              Your accountability check-in. About{" "}
              {Math.round((call?.max_duration_seconds ?? 120) / 60)} minutes. Stops ringing in{" "}
              {formatClock(ringLeft)}.
            </p>
          </>
        )}
        {phase === "connecting" && <h1 className="text-2xl font-semibold">Connecting…</h1>}
        {phase === "live" && (
          <>
            <p className="text-sm uppercase tracking-[0.3em] text-moss">On call with Bhima</p>
            <h1 className="font-mono text-4xl">{formatClock(elapsed)}</h1>
            <p className="text-sm text-foreground/60">
              {conversation.isSpeaking ? "Bhima is speaking" : "Listening"}
            </p>
          </>
        )}
        {phase === "ended" && (
          <>
            <h1 className="text-2xl font-semibold">Call ended</h1>
            <p className="text-foreground/70">Nice work. Your commitments are saved.</p>
          </>
        )}
        {phase === "missed" && (
          <>
            <h1 className="text-2xl font-semibold">This call is no longer ringing</h1>
            <p className="text-foreground/70">
              It was missed, answered elsewhere or cancelled. Bhima will not call back, and your
              next scheduled call is unaffected.
            </p>
          </>
        )}
        {phase === "declined" && <h1 className="text-2xl font-semibold">Call declined</h1>}
        {error && (
          <p role="alert" className="text-bloom">
            {error}
          </p>
        )}
      </div>

      <div className="flex gap-4">
        {phase === "ringing" && (
          <>
            <button
              onClick={decline}
              className="rounded-full border border-white/20 px-6 py-3 transition hover:bg-white/5"
            >
              Decline
            </button>
            <button
              onClick={answer}
              autoFocus
              className="rounded-full bg-moss px-8 py-3 font-medium text-night transition hover:brightness-110"
            >
              Answer
            </button>
          </>
        )}
        {phase === "live" && (
          <>
            <button
              onClick={() => conversation.setMuted(!conversation.isMuted)}
              aria-pressed={conversation.isMuted}
              className="rounded-full border border-white/20 px-6 py-3 transition hover:bg-white/5"
            >
              {conversation.isMuted ? "Unmute" : "Mute"}
            </button>
            <button
              onClick={hangUp}
              className="rounded-full bg-bloom px-8 py-3 font-medium text-night transition hover:brightness-110"
            >
              Hang up
            </button>
          </>
        )}
        {(phase === "ended" || phase === "missed" || phase === "declined" || phase === "error") && (
          <>
            <Link
              href="/garden"
              className="rounded-full bg-moss px-6 py-3 font-medium text-night transition hover:brightness-110"
            >
              Back to my garden
            </Link>
            <Link
              href="/settings/schedule"
              className="rounded-full border border-white/20 px-6 py-3 transition hover:bg-white/5"
            >
              Call schedule
            </Link>
          </>
        )}
      </div>
    </main>
  );
}

function Avatar({ pulsing }: { pulsing: boolean }) {
  return (
    <div className="relative grid size-36 place-items-center" aria-hidden>
      {pulsing && (
        <span className="absolute inset-0 animate-ping rounded-full bg-moss/30 motion-reduce:hidden" />
      )}
      <span className="relative grid size-32 place-items-center rounded-full border border-white/15 bg-dusk text-5xl font-semibold text-glow">
        B
      </span>
    </div>
  );
}
