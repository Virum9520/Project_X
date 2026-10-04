"use client";

import type { GardenDataset, LiveGrowthEvent } from "@sg/contracts";
import { useCallback, useEffect, useReducer, useRef, useState } from "react";

import { CharacterAvatar } from "@/components/character/character-avatar";
import { ScheduleSettings } from "@/components/accountability/schedule-settings";
import { ErrorBanner } from "@/components/session/stage-chrome";
import { EvidenceTicker } from "@/components/session/stage-parts";
import { formatClock } from "@/lib/accountability/helpers";
import type { Schedule } from "@/lib/accountability/types";
import { plantsAt } from "@/lib/garden/derive";
import { DEFAULT_STATE } from "@/lib/garden/state";
import { conceptByKey, useBank, type Bank, type BankConcept } from "@/lib/practice/bank";
import { lowerFirst, pick, sentence, todoLine } from "@/lib/practice/coach-lines";
import {
  recordPractice,
  toLiveEvent,
  usePracticeDataset,
  type EvidenceDraft,
} from "@/lib/practice/dataset";
import { broadcastGrowth } from "@/lib/practice/live";
import { judgeAgainstRubric } from "@/lib/practice/scoring";
import { useCoachVoice, useVoiceMuted } from "@/lib/practice/speech";
import { newId, readRecords, subscribeRecords } from "@/lib/practice/store";
import { INITIAL_STAGE, stageReducer } from "@/lib/session/stage";
import { useLiveGrowth } from "@/lib/session/use-live-growth";

import {
  AnswerBox,
  CoachPortrait,
  LoadingPanel,
  PrimaryButton,
  SecondaryButton,
  SessionSummary,
  Transcript,
  VoiceToggle,
  useTurnLog,
  type EarnedItem,
} from "./conversation";

const RING_TIMEOUT_MS = 45_000;
const DONE =
  /\b(yes|yeah|yep|did|done|finished|completed|managed|both|kept|on track|went well|nailed)\b/i;
const NOT_DONE =
  /\b(didn'?t|did not|not yet|no|nope|missed|couldn'?t|failed|skipped|forgot|busy)\b/i;

/** Two-tone ring from the Web Audio API (no audio files needed). */
function useRingTone(active: boolean) {
  const muted = useVoiceMuted();
  useEffect(() => {
    if (!active || muted) return;
    const Ctx =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const ring = () => {
      const t = ctx.currentTime;
      for (const [offset, freq] of [
        [0, 880],
        [0.28, 660],
      ] as const) {
        const osc = ctx.createOscillator();
        const gain = ctx.createGain();
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(0.0001, t + offset);
        gain.gain.exponentialRampToValueAtTime(0.12, t + offset + 0.02);
        gain.gain.exponentialRampToValueAtTime(0.0001, t + offset + 0.24);
        osc.connect(gain).connect(ctx.destination);
        osc.start(t + offset);
        osc.stop(t + offset + 0.26);
      }
    };
    ring();
    const id = window.setInterval(ring, 2200);
    return () => {
      window.clearInterval(id);
      void ctx.close();
    };
  }, [active, muted]);
}

/** A concept Bhima can quiz: a wilting plant first, else the one practised longest ago. */
function retentionConcept(bank: Bank, dataset: GardenDataset): BankConcept | null {
  const plants = plantsAt(dataset, DEFAULT_STATE.filters, Date.parse(dataset.generatedAt)).filter(
    (p) => p.stage !== "unassessed" && p.meta.grove !== "behavioral",
  );
  const ordered = [
    ...plants.filter((p) => p.wilting),
    ...plants
      .filter((p) => !p.wilting)
      .sort((a, b) => (a.lastEvidenceAt ?? "").localeCompare(b.lastEvidenceAt ?? "")),
  ];
  for (const p of ordered) {
    const c = conceptByKey(bank, p.meta.key);
    if (c?.rubric.explanation?.length) return c;
  }
  return null;
}

type Step = "commitment" | "new_commitment" | "retention" | "done";

export function BhimaCall({
  bank,
  dataset,
  onClose,
}: {
  bank: Bank;
  dataset: GardenDataset;
  onClose: () => void;
}) {
  const voice = useCoachVoice("bhima");
  const [turns, addTurn] = useTurnLog();
  const [stage, dispatch] = useReducer(stageReducer, INITIAL_STAGE);
  const [phase, setPhase] = useState<"ringing" | "live" | "ended" | "missed">("ringing");
  const [step, setStep] = useState<Step>("commitment");
  const [draft, setDraft] = useState("");
  // The learner may answer as soon as Bhima has asked, even mid-sentence.
  const [awaiting, setAwaiting] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<{
    earned: EarnedItem[];
    saved: boolean;
    commitment: string | null;
  } | null>(null);
  const [concept] = useState(() => retentionConcept(bank, dataset));
  const startedAt = useRef(0);
  const sessionId = useRef(newId("ses"));
  const evidence = useRef<EvidenceDraft[]>([]);
  const promise = useRef<string | null>(null);
  const active = useRef(false);
  // A newer turn (an answer that interrupts) makes an older flow stop at its next await.
  const flow = useRef(0);
  const startFlow = () => {
    const id = ++flow.current;
    return () => active.current && flow.current === id;
  };
  useRingTone(phase === "ringing");

  useLiveGrowth({
    enabled: phase === "live" || phase === "ended",
    onEvent: useCallback((e: LiveGrowthEvent) => dispatch({ type: "growth", event: e }), []),
  });

  useEffect(() => {
    if (phase !== "ringing") return;
    const id = window.setTimeout(() => setPhase("missed"), RING_TIMEOUT_MS);
    return () => window.clearTimeout(id);
  }, [phase]);

  useEffect(() => {
    if (phase !== "live") return;
    const id = window.setInterval(
      () => setElapsed(Math.floor((Date.now() - startedAt.current) / 1000)),
      1000,
    );
    return () => window.clearInterval(id);
  }, [phase]);

  const commitment = [...dataset.memories].reverse().find((m) => m.layer === "commitments");

  async function say(text: string) {
    addTurn("bhima", text);
    await voice.say(text);
  }

  async function accept() {
    active.current = true;
    startedAt.current = Date.now();
    setPhase("live");
    startFlow();
    setAwaiting(true);
    await say(
      commitment
        ? `Hey, it's Bhima! Quick check-in. ${
            /^committed to /i.test(commitment.text)
              ? `Last time you ${lowerFirst(commitment.text.replace(/\.$/, ""))}.`
              : `Last time you told me: ${lowerFirst(commitment.text.replace(/\.$/, ""))}.`
          } How did it go?`
        : "Hey, it's Bhima! Quick check-in. What did you get done since we last spoke?",
    );
  }

  async function askRetention() {
    setStep("retention");
    if (!concept) {
      await say("Nothing is due for review right now. Nice work keeping your garden fresh.");
      await wrapUp();
      return;
    }
    setAwaiting(true);
    await say(
      `Now a quick one from a while back: ${concept.title}. Explain it to me in a sentence or two.`,
    );
  }

  async function wrapUp() {
    if (!active.current) return;
    active.current = false;
    flow.current += 1;
    setAwaiting(false);
    voice.silence();
    setStep("done");
    const recorded = recordPractice({
      character: "bhima",
      title: "Bhima: daily check-in",
      startedAt: startedAt.current,
      endedAt: Date.now(),
      evidence: evidence.current,
      memories: promise.current
        ? [
            {
              layer: "commitments",
              text: promise.current,
              why: "You told Bhima on a check-in call.",
              affects: [],
            },
          ]
        : [],
    });
    setResult({
      saved: recorded.saved,
      commitment: promise.current,
      earned: evidence.current.map((d) => ({
        plantTitle: concept?.title ?? d.plantKey,
        dimension: d.dimension,
        outcome: d.outcome,
        assisted: d.kind === "assisted",
        quote: d.quote,
      })),
    });
    setPhase("ended");
    await say(
      pick([
        "That's our check-in. Talk soon!",
        "Done! Go water that garden.",
        "That's it for today. Proud of you.",
      ]),
    );
  }

  async function submit(text: string) {
    if (!awaiting || phase !== "live") return;
    const current = startFlow();
    setAwaiting(false);
    voice.silence();
    setDraft("");
    addTurn("you", text);
    if (step === "commitment") {
      if (DONE.test(text) && !NOT_DONE.test(text)) {
        await say(
          pick([
            "Love it. That's how plants grow.",
            "Yes! Consistency beats cramming.",
            "Great work. Keep that streak alive.",
          ]),
        );
        if (current()) await askRetention();
      } else {
        setStep("new_commitment");
        setAwaiting(true);
        await say(
          "No stress, that happens. What's one small thing you'll do before our next call?",
        );
      }
      return;
    }
    if (step === "new_commitment") {
      promise.current = sentence(text.slice(0, 200));
      await say("Got it. I'll hold you to that.");
      if (current()) await askRetention();
      return;
    }
    if (step === "retention" && concept) {
      const criteria = concept.rubric.explanation ?? [];
      const judged = judgeAgainstRubric(text, criteria);
      if (judged.outcome !== "not_demonstrated") {
        const draftItem: EvidenceDraft = {
          plantKey: concept.key,
          dimension: "retention",
          kind: "independent",
          outcome: judged.outcome,
          quote: text,
          source: "transcript",
          rationale: `Recalled ${concept.title} on a check-in call without notice.`,
          confidence: judged.confidence,
        };
        evidence.current.push(draftItem);
        const event = toLiveEvent(
          { ...draftItem, sessionId: sessionId.current },
          "provisional",
          judged.outcome,
        );
        dispatch({ type: "growth", event });
        broadcastGrowth(event);
      }
      const missed = judged.missed[0]?.criterion ?? criteria[0] ?? "";
      await say(
        judged.outcome === "demonstrated"
          ? `Still there! Your ${concept.title.toLowerCase()} plant is blooming.`
          : judged.outcome === "partial"
            ? `Mostly there. Next time, ${todoLine(missed)}. Worth a quick review.`
            : `That one's fading. The key idea: a good answer would ${todoLine(missed)}. Review it this week.`,
      );
      await wrapUp();
    }
  }

  if (phase === "ringing" || phase === "missed") {
    return (
      <section
        className="glass flex flex-col items-center gap-4 rounded-3xl p-6 text-center"
        aria-label="Incoming call from Bhima"
        aria-live="assertive"
      >
        <CharacterAvatar character="bhima" size={150} speaking={phase === "ringing"} />
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-glow">
            {phase === "ringing" ? "Incoming call" : "Missed call"}
          </p>
          <h2 className="mt-1 text-2xl font-semibold">Bhima</h2>
          <p className="text-sm text-foreground/60">Accountability check-in · about 2 minutes</p>
        </div>
        <div className="flex gap-3">
          {phase === "ringing" ? (
            <>
              <PrimaryButton tone="moss" onClick={() => void accept()}>
                Accept
              </PrimaryButton>
              <PrimaryButton tone="ember" onClick={onClose}>
                Decline
              </PrimaryButton>
            </>
          ) : (
            <>
              <PrimaryButton tone="moss" onClick={() => void accept()}>
                Call back
              </PrimaryButton>
              <SecondaryButton onClick={onClose}>Close</SecondaryButton>
            </>
          )}
        </div>
      </section>
    );
  }

  return (
    <section className="flex flex-col gap-3" aria-label="Call with Bhima">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-foreground/70">
          {phase === "live" ? `On a call with Bhima · ${formatClock(elapsed)}` : "Call ended"}
        </p>
        <div className="flex items-center gap-2">
          <VoiceToggle />
          {phase === "live" ? (
            <PrimaryButton tone="ember" onClick={() => void wrapUp()}>
              Hang up
            </PrimaryButton>
          ) : (
            <SecondaryButton onClick={onClose}>Close</SecondaryButton>
          )}
        </div>
      </div>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[14rem_minmax(0,1fr)]">
        <CoachPortrait
          character="bhima"
          driver={voice.lipSync}
          status={phase === "live" ? (voice.speaking ? "Bhima is speaking" : "Your turn") : "Bhima"}
          className="h-56"
        />
        <div className="flex min-w-0 flex-col gap-3">
          <Transcript turns={turns} empty="" />
          {phase === "live" && step !== "done" && (
            <AnswerBox
              value={draft}
              onChange={setDraft}
              onSubmit={(text) => void submit(text)}
              disabled={!awaiting}
              placeholder={
                step === "retention" ? "Explain it in a sentence or two…" : "Tell Bhima…"
              }
            />
          )}
        </div>
      </div>
      {phase === "ended" && result && (
        <SessionSummary
          title="Check-in with Bhima"
          earned={result.earned}
          saved={result.saved}
          notes={result.commitment ? [`New commitment: ${result.commitment}`] : []}
          onAgain={onClose}
          againLabel="Done"
        />
      )}
      <EvidenceTicker entries={stage.ticker} />
    </section>
  );
}

/** ISO weekday (1 = Monday) and `HH:MM` in the browser's time zone. */
function localNow() {
  const d = new Date();
  return {
    day: ((d.getDay() + 6) % 7) + 1,
    time: `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`,
    date: d.toDateString(),
  };
}

/** Rings while this page is open when one of the learner's call times arrives. */
function useScheduledRing(onRing: () => void) {
  const rung = useRef(new Set<string>());
  const onRingRef = useRef(onRing);
  useEffect(() => {
    onRingRef.current = onRing;
  });
  useEffect(() => {
    const check = () => {
      const now = localNow();
      const due = readRecords().schedules.find(
        (s: Schedule) => s.enabled && s.days.includes(now.day) && s.local_time === now.time,
      );
      if (!due) return;
      const key = `${due.id}:${now.date}:${now.time}`;
      if (rung.current.has(key)) return;
      rung.current.add(key);
      onRingRef.current();
    };
    const id = window.setInterval(check, 15_000);
    const stop = subscribeRecords(check);
    return () => {
      window.clearInterval(id);
      stop();
    };
  }, []);
}

export function BhimaPage() {
  const dataset = usePracticeDataset();
  const { bank, error } = useBank();
  const [calling, setCalling] = useState(0);
  const ring = useCallback(() => setCalling((n) => (n === 0 ? Date.now() : n)), []);
  useScheduledRing(ring);
  const tz = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-6 pb-16 pt-32">
      <header>
        <p className="text-sm uppercase tracking-[0.3em] text-glow">Bhima · Accountability</p>
        <h1 className="mt-2 text-3xl font-semibold">Your check-in calls</h1>
        <p className="mt-3 text-foreground/70">
          Bhima rings you at the times you pick, asks what you committed to, and checks one concept
          you learned a while ago. Calls are short, never during quiet hours, and you can stop them
          at any time.
        </p>
      </header>

      {error && <ErrorBanner message={error} />}
      {calling > 0 && bank ? (
        <BhimaCall key={calling} bank={bank} dataset={dataset} onClose={() => setCalling(0)} />
      ) : (
        <section className="glass flex flex-wrap items-center justify-between gap-4 rounded-2xl p-5">
          <div>
            <h2 className="font-medium">Talk to Bhima now</h2>
            <p className="text-sm text-foreground/70">
              A two-minute check-in: your commitment, then one quick memory question.
            </p>
          </div>
          {bank ? (
            <PrimaryButton tone="moss" onClick={() => setCalling(Date.now())}>
              Call me now
            </PrimaryButton>
          ) : (
            !error && <LoadingPanel label="Getting Bhima ready…" />
          )}
        </section>
      )}

      <ScheduleSettings defaultTz={tz} showPush={false} />
      <p className="text-xs text-foreground/50">
        Scheduled calls ring on this page while it is open in your browser.
      </p>
    </main>
  );
}
