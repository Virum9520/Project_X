"use client";

import { CommitStrategy, useScribe } from "@elevenlabs/react";
import { useCallback, useEffect, useRef, useState } from "react";

import { appendCaption, clock, type CaptionLine } from "@/lib/arjuna/captions";

export type ScribeTokenFetcher = () => Promise<
  { ok: true; token: string; modelId: string } | { ok: false; message: string }
>;

/**
 * Live think-aloud captions beside the editor, from ElevenLabs realtime Scribe.
 *
 * It opens its own microphone stream next to the voice conversation's (browsers allow several
 * streams of one microphone), authenticated with a single-use token minted by our API, so the
 * provider key never reaches the browser. The transcript is shown for the candidate and kept in
 * memory only: nothing here is uploaded, and the evidence pipeline reads the conversation
 * transcript, not this one.
 */
export function ThinkAloud({
  active,
  startedAt,
  fetchToken,
}: {
  active: boolean;
  /** `Date.now()` when the interview started, for the timestamps. */
  startedAt: number | null;
  fetchToken: ScribeTokenFetcher;
}) {
  const [lines, setLines] = useState<CaptionLine[]>([]);
  const [notice, setNotice] = useState<string | null>(null);
  const startedRef = useRef(startedAt);
  useEffect(() => {
    startedRef.current = startedAt;
  });

  const scribe = useScribe({
    modelId: "scribe_v2_realtime",
    commitStrategy: CommitStrategy.VAD,
    microphone: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    onCommittedTranscript: ({ text }) => {
      const at = startedRef.current === null ? 0 : Date.now() - startedRef.current;
      setLines((prev) => appendCaption(prev, text, at));
    },
    onError: () => setNotice("Live captions stopped. The interview continues without them."),
    onAuthError: () => setNotice("Live captions could not authenticate."),
    onQuotaExceededError: () => setNotice("Live captions are paused (provider quota)."),
  });

  const { connect, disconnect, isConnected } = scribe;
  const connecting = useRef(false);
  const start = useCallback(async () => {
    if (connecting.current) return;
    connecting.current = true;
    setNotice(null);
    try {
      const result = await fetchToken();
      if (!result.ok) {
        setNotice(result.message);
        return;
      }
      await connect({ token: result.token, modelId: result.modelId });
    } catch {
      setNotice("Live captions could not start. Check microphone access.");
    } finally {
      connecting.current = false;
    }
  }, [connect, fetchToken]);

  useEffect(() => {
    if (!active) return undefined;
    const timer = window.setTimeout(() => void start(), 0);
    return () => {
      window.clearTimeout(timer);
      disconnect();
    };
  }, [active, start, disconnect]);

  return (
    <section aria-label="Think-aloud captions" className="glass rounded-2xl p-4">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-[0.7rem] font-medium uppercase tracking-[0.22em] text-foreground/60">
          Think-aloud captions
        </h2>
        <span
          className={`text-xs ${isConnected ? "text-moss" : "text-foreground/50"}`}
          role="status"
        >
          {isConnected ? "Listening" : active ? "Connecting…" : "Idle"}
        </span>
      </div>
      {notice && (
        <p role="alert" className="mt-2 rounded-lg bg-ember/10 px-3 py-1.5 text-xs text-ember">
          {notice}
        </p>
      )}
      <div
        className="mt-2 flex max-h-40 flex-col gap-1 overflow-y-auto text-sm"
        role="log"
        aria-live="polite"
      >
        {lines.length === 0 && !scribe.partialTranscript && (
          <p className="text-foreground/50">
            Talk through your approach while you code. Your words appear here.
          </p>
        )}
        {lines.map((l) => (
          <p key={l.id} className="text-foreground/80">
            <span className="mr-2 font-mono text-xs text-foreground/40">{clock(l.atMs)}</span>
            {l.text}
          </p>
        ))}
        {scribe.partialTranscript && (
          <p className="text-foreground/50">
            <span className="mr-2 font-mono text-xs text-foreground/30">…</span>
            {scribe.partialTranscript}
          </p>
        )}
      </div>
    </section>
  );
}
