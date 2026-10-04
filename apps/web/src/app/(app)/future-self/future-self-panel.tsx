"use client";

import type {
  ConsentChallenge,
  ConsentRecordingResult,
  ConsentStatus,
  FutureSelfMessage,
} from "@sg/contracts";
import { useRef, useState } from "react";

const BASE = "/api/future-self";

type Step = "idle" | "ready" | "recording" | "checking" | "revoking" | "speaking";

async function call<T>(path: string, init?: RequestInit): Promise<T | null> {
  const response = await fetch(`${BASE}/${path}`, { ...init, cache: "no-store" });
  if (response.status === 204) return null;
  const body = (await response.json().catch(() => ({}))) as {
    detail?: string | { message?: string };
  };
  if (!response.ok) {
    const detail = body.detail;
    throw new Error(
      (typeof detail === "string" ? detail : detail?.message) ??
        `Request failed (${response.status})`,
    );
  }
  return body as T;
}

function pickMimeType(): string | undefined {
  if (typeof MediaRecorder === "undefined") return undefined;
  return ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"].find((t) =>
    MediaRecorder.isTypeSupported(t),
  );
}

export function FutureSelfPanel({ initial }: { initial: ConsentStatus }) {
  const [status, setStatus] = useState(initial);
  const [step, setStep] = useState<Step>("idle");
  const [accepted, setAccepted] = useState(false);
  const [challenge, setChallenge] = useState<ConsentChallenge | null>(null);
  const [message, setMessage] = useState<FutureSelfMessage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const [confirmRevoke, setConfirmRevoke] = useState(false);
  const recorder = useRef<MediaRecorder | null>(null);
  const busy = step === "checking" || step === "revoking" || step === "speaking";

  async function run<T>(next: Step, work: () => Promise<T>): Promise<T | undefined> {
    setError(null);
    setNote(null);
    setStep(next);
    try {
      return await work();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong.");
      return undefined;
    }
  }

  async function getPhrase() {
    const c = await run("checking", () =>
      call<ConsentChallenge>("consent/challenge", { method: "POST" }),
    );
    setChallenge(c ?? null);
    setStep(c ? "ready" : "idle");
  }

  async function startRecording() {
    if (!challenge) return;
    setError(null);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const mimeType = pickMimeType();
      const rec = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      const chunks: Blob[] = [];
      rec.ondataavailable = (e) => chunks.push(e.data);
      rec.onstop = () => {
        stream.getTracks().forEach((t) => t.stop());
        void upload(
          new Blob(chunks, { type: rec.mimeType || mimeType || "audio/webm" }),
          challenge,
        );
      };
      recorder.current = rec;
      rec.start();
      setStep("recording");
    } catch {
      setError("We could not use your microphone. Allow access and try again.");
    }
  }

  async function upload(blob: Blob, c: ConsentChallenge) {
    const result = await run("checking", () =>
      call<ConsentRecordingResult>("consent/recording", {
        method: "POST",
        body: blob,
        headers: {
          "Content-Type": blob.type,
          "X-Consent-Challenge": c.challenge_token,
          "X-Consent-Accepted": "true",
        },
      }),
    );
    if (!result) {
      setStep("idle");
      setChallenge(null);
      return;
    }
    setStatus(result.status);
    if (result.verified) {
      setChallenge(null);
      setAccepted(false);
      setStep("idle");
      setNote("Your Future-Self voice is ready.");
    } else {
      setStep("ready");
      setError(
        `We could not match what you said to the phrase${
          result.words_heard ? "" : " (the code words were not heard)"
        }. Nothing was saved. Read it again, clearly.`,
      );
    }
  }

  function stopRecording() {
    recorder.current?.stop();
  }

  async function hearMessage() {
    const m = await run("speaking", () => call<FutureSelfMessage>("message", { method: "POST" }));
    setStep("idle");
    if (m) {
      setMessage(m);
      void new Audio(`data:${m.media_type};base64,${m.audio_base64}`).play().catch(() => {});
    }
  }

  async function revoke() {
    const ok = await run("revoking", async () => {
      await call("consent", { method: "DELETE" });
      return true;
    });
    setStep("idle");
    setConfirmRevoke(false);
    if (ok) {
      setMessage(null);
      setStatus((await call<ConsentStatus>("consent")) ?? status);
      setNote("Deleted. Your voice is removed at ElevenLabs and your recording is erased.");
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <div aria-live="polite" className="flex flex-col gap-2">
        {error && (
          <p
            role="alert"
            className="rounded-lg border border-bloom/40 bg-dusk/60 px-4 py-3 text-bloom"
          >
            {error}
          </p>
        )}
        {note && (
          <p className="rounded-lg border border-moss/40 bg-dusk/60 px-4 py-3 text-moss">{note}</p>
        )}
      </div>

      {status.active ? (
        <section className="flex flex-col gap-4 rounded-xl border border-white/10 bg-dusk/60 p-6">
          <h2 className="font-medium">Your Future-Self voice is on</h2>
          <p className="text-sm text-foreground/70">
            Consent {status.current?.consent_version} given{" "}
            {status.current && new Date(status.current.created_at).toLocaleString()}. Used only for
            your daily message.
          </p>
          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={hearMessage}
              disabled={busy}
              className="rounded-lg bg-moss px-4 py-2 font-medium text-night disabled:opacity-50"
            >
              {step === "speaking" ? "Writing your message…" : "Hear today's message"}
            </button>
            {confirmRevoke ? (
              <span className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={revoke}
                  disabled={busy}
                  className="rounded-lg bg-bloom px-4 py-2 font-medium text-night disabled:opacity-50"
                >
                  {step === "revoking" ? "Deleting…" : "Yes, delete my voice"}
                </button>
                <button
                  type="button"
                  onClick={() => setConfirmRevoke(false)}
                  className="rounded-lg border border-white/20 px-4 py-2"
                >
                  Keep it
                </button>
              </span>
            ) : (
              <button
                type="button"
                onClick={() => setConfirmRevoke(true)}
                disabled={busy}
                className="rounded-lg border border-bloom/60 px-4 py-2 text-bloom disabled:opacity-50"
              >
                Revoke and delete
              </button>
            )}
          </div>
          {message && (
            <figure className="flex flex-col gap-2 border-t border-white/10 pt-4">
              <audio
                controls
                src={`data:${message.media_type};base64,${message.audio_base64}`}
                className="w-full"
              />
              <figcaption className="text-sm italic text-foreground/70">
                {message.script}
              </figcaption>
            </figure>
          )}
        </section>
      ) : (
        <section className="flex flex-col gap-4 rounded-xl border border-white/10 bg-dusk/60 p-6">
          <h2 className="font-medium">Consent</h2>
          <ul className="list-disc space-y-1 pl-5 text-sm text-foreground/80">
            {status.statements.map((s) => (
              <li key={s}>{s}</li>
            ))}
          </ul>
          {!challenge && (
            <>
              <label className="flex items-start gap-3 text-sm">
                <input
                  type="checkbox"
                  checked={accepted}
                  onChange={(e) => setAccepted(e.target.checked)}
                  className="mt-1 accent-moss"
                />
                <span>I have read this and it is my own voice that I will record.</span>
              </label>
              <button
                type="button"
                onClick={getPhrase}
                disabled={!accepted || busy}
                className="self-start rounded-lg bg-moss px-4 py-2 font-medium text-night disabled:opacity-50"
              >
                Get my phrase
              </button>
            </>
          )}
          {challenge && (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-foreground/70">
                Read this aloud, in your own voice, in a quiet room:
              </p>
              <blockquote className="rounded-lg border border-glow/30 bg-night px-4 py-3 text-lg">
                {challenge.phrase}
              </blockquote>
              <div className="flex gap-3">
                {step === "recording" ? (
                  <button
                    type="button"
                    onClick={stopRecording}
                    className="rounded-lg bg-bloom px-4 py-2 font-medium text-night"
                  >
                    Stop and check
                  </button>
                ) : (
                  <button
                    type="button"
                    onClick={startRecording}
                    disabled={busy}
                    className="rounded-lg bg-moss px-4 py-2 font-medium text-night disabled:opacity-50"
                  >
                    {step === "checking" ? "Checking…" : "Start recording"}
                  </button>
                )}
                <button
                  type="button"
                  onClick={() => {
                    setChallenge(null);
                    setStep("idle");
                  }}
                  disabled={busy || step === "recording"}
                  className="rounded-lg border border-white/20 px-4 py-2 disabled:opacity-50"
                >
                  Cancel
                </button>
              </div>
              <p className="text-xs text-foreground/50">
                The phrase expires in 10 minutes. If the check fails, nothing is saved.
              </p>
            </div>
          )}
        </section>
      )}

      {status.history.length > 0 && (
        <section className="rounded-xl border border-white/10 bg-dusk/60 p-6">
          <h2 className="font-medium">Consent record</h2>
          <ul className="mt-3 space-y-2 text-sm text-foreground/70">
            {status.history.map((r) => (
              <li key={r.id}>
                {new Date(r.created_at).toLocaleString()} · {r.consent_version} ·{" "}
                {r.revoked_at
                  ? `revoked ${new Date(r.revoked_at).toLocaleString()} (voice and recording deleted)`
                  : "active"}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}
