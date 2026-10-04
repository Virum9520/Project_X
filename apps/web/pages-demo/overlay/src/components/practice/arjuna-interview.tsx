"use client";

import type {
  AgentRun,
  ArjunaPlan,
  GardenDataset,
  LiveGrowthEvent,
  RunnableLanguage,
} from "@sg/contracts";
import { RUNNABLE_LANGUAGES } from "@sg/contracts";
import { useCallback, useMemo, useReducer, useRef, useState } from "react";

import { PlanCard } from "@/components/arjuna/plan-card";
import { ErrorBanner } from "@/components/session/stage-chrome";
import { EvidenceTicker } from "@/components/session/stage-parts";
import { RUNNABLE_LABELS } from "@/lib/arjuna/language";
import { useBank, type Bank, type BankProblem } from "@/lib/practice/bank";
import { pick } from "@/lib/practice/coach-lines";
import { recordPractice, toLiveEvent, usePracticeDataset } from "@/lib/practice/dataset";
import { broadcastGrowth } from "@/lib/practice/live";
import { buildPlan, problemsForConcept, selectProblem } from "@/lib/practice/problems";
import { judgeAgainstRubric } from "@/lib/practice/scoring";
import { useCoachVoice } from "@/lib/practice/speech";
import { newId, readRecords } from "@/lib/practice/store";
import { INITIAL_STAGE, stageReducer } from "@/lib/session/stage";
import { useLiveGrowth } from "@/lib/session/use-live-growth";

import { useCodingRound } from "./coding-round";
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

const RUN_TESTS = /\b(run|try|check)\b.*\btests?\b|\bsubmit\b/i;
const WANT_HINT = /\bhint\b|\bstuck\b/i;
const NEXT_PROBLEM = /\b(next|another|new)\b.*\b(problem|question|one)\b/i;

function planFor(bank: Bank, dataset: GardenDataset): { plan: ArjunaPlan; first: string | null } {
  const saved = readRecords().plan;
  const plan = buildPlan(bank, {
    role: saved?.role ?? dataset.readiness.targetRole,
    resume: saved?.resume ?? "",
    jobDescription: saved?.jobDescription ?? "",
  });
  const concept = new URLSearchParams(window.location.search).get("concept");
  if (concept && bank.concepts.some((c) => c.key === concept)) {
    plan.probes = [concept, ...plan.probes.filter((p) => p !== concept)].slice(0, 6);
    return { plan, first: concept };
  }
  return { plan, first: plan.problems[0]?.concept_id ?? plan.probes[0] ?? null };
}

export function ArjunaInterview() {
  const dataset = usePracticeDataset();
  const { bank, error } = useBank();
  return (
    <main className="mx-auto flex w-full max-w-[1400px] flex-1 flex-col gap-4 px-4 pb-16 pt-24 sm:px-6">
      {error ? (
        <ErrorBanner message={error} />
      ) : bank ? (
        <ArjunaStage bank={bank} dataset={dataset} />
      ) : (
        <LoadingPanel label="Arjuna is getting ready…" />
      )}
    </main>
  );
}

function ArjunaStage({ bank, dataset }: { bank: Bank; dataset: GardenDataset }) {
  const [{ plan, first }] = useState(() => planFor(bank, dataset));
  const voice = useCoachVoice("arjuna");
  const [turns, addTurn, clearTurns] = useTurnLog();
  const [stage, dispatch] = useReducer(stageReducer, INITIAL_STAGE);
  const [phase, setPhase] = useState<"setup" | "live" | "ended">("setup");
  const [language, setLanguage] = useState<RunnableLanguage>("python");
  const [draft, setDraft] = useState("");
  // True while Arjuna sets up a problem or wraps up; otherwise the learner can talk any time,
  // and a new message interrupts whatever Arjuna is saying.
  const [opening, setOpening] = useState(false);
  const [pending, setPending] = useState<"approach" | null>(null);
  const [result, setResult] = useState<{ earned: EarnedItem[]; saved: boolean } | null>(null);
  const startedAt = useRef(0);
  const sessionId = useRef("");
  const active = useRef(false);
  const titleOf = useMemo(() => new Map(bank.concepts.map((c) => [c.key, c.title])), [bank]);

  const voiceSay = voice.say;
  const say = useCallback(
    async (text: string) => {
      addTurn("arjuna", text);
      await voiceSay(text);
    },
    [addTurn, voiceSay],
  );
  // A full run passing at least half the cases glows provisionally, like the live judge.
  const onRun = useCallback((run: AgentRun, problem: BankProblem) => {
    if (run.passed / Math.max(1, run.total) < 0.5) return;
    const event = toLiveEvent(
      {
        plantKey: problem.concept_id,
        dimension: "application",
        kind: run.assisted ? "assisted" : "independent",
        quote: run.summary,
        sessionId: sessionId.current,
      },
      "provisional",
      run.status === "passed" ? "demonstrated" : "partial",
    );
    dispatch({ type: "growth", event });
    broadcastGrowth(event);
  }, []);
  const round = useCodingRound({ say, onRun });
  const live = useLiveGrowth({
    enabled: phase !== "setup",
    onEvent: useCallback((e: LiveGrowthEvent) => dispatch({ type: "growth", event: e }), []),
  });

  async function openProblem(problem: BankProblem, intro: string) {
    round.open(problem, language);
    setPending("approach");
    setOpening(false);
    await say(
      `${intro} ${problem.title}. Before you code, tell me your approach in a sentence or two.`,
    );
  }

  async function begin() {
    const firstProblem = selectProblem(bank, first).problem;
    sessionId.current = newId("ses");
    startedAt.current = Date.now();
    active.current = true;
    round.reset();
    clearTurns();
    dispatch({ type: "reset" });
    setResult(null);
    setPhase("live");
    setOpening(true);
    const focus = first ? titleOf.get(first) : null;
    const topic = focus ? focus.toLowerCase() : "a coding problem";
    await say(
      `Hi, I'm Arjuna. ${
        plan.grounded
          ? `I read your ${plan.has_job_description ? "job description" : "résumé"}, so we'll start with ${topic}.`
          : `We'll start with ${topic}.`
      } Think out loud as you go, typed or spoken; I'm listening.`,
    );
    if (active.current) await openProblem(firstProblem, "Here's the problem:");
  }

  async function advance() {
    const done = round.attempted();
    const solvedAlone = done.some((a) => a.best?.status === "passed" && a.hints === 0);
    const nextConcept =
      plan.probes.find(
        (k) => problemsForConcept(bank, k).length && !done.some((a) => a.problem.concept_id === k),
      ) ??
      round.problem?.concept_id ??
      null;
    const { problem } = selectProblem(bank, nextConcept, {
      exclude: new Set(done.map((a) => a.problem.id)),
      excludeFamilies: new Set(done.map((a) => a.problem.family)),
      harder: solvedAlone,
    });
    await openProblem(problem, solvedAlone ? "Let's step it up:" : "Here's another one:");
  }

  async function nextProblem() {
    if (opening) return;
    setOpening(true);
    await advance();
  }

  async function finish() {
    if (!active.current) return;
    active.current = false;
    setOpening(true);
    voice.silence();
    const evidence = round.evidence();
    const recorded = recordPractice({
      character: "arjuna",
      title: `Arjuna: ${round.attempted()[0]?.problem.title ?? "Technical interview"}`,
      startedAt: startedAt.current,
      endedAt: Date.now(),
      evidence,
    });
    setResult({
      saved: recorded.saved,
      earned: evidence.map((d) => ({
        plantTitle: titleOf.get(d.plantKey) ?? d.plantKey,
        dimension: d.dimension,
        outcome: d.outcome,
        assisted: d.kind === "assisted",
        quote: d.source === "tests" ? d.rationale : d.quote,
      })),
    });
    setPhase("ended");
    setPending(null);
    await say(
      evidence.length
        ? "That's time. Thanks, that was a good session. Your results are in your garden."
        : "That's time. No passing runs today, but the practice counts: come back and try again.",
    );
    setOpening(false);
  }

  async function submit(text: string) {
    if (opening || phase !== "live") return;
    voice.silence();
    setDraft("");
    addTurn("you", text);
    if (round.askedComplexity) {
      const { reply, outcome } = round.answerComplexity(text);
      if (outcome && round.problem) {
        const solved = round.attempted().find((a) => a.problem.id === round.problem?.id);
        const event = toLiveEvent(
          {
            plantKey: round.problem.concept_id,
            dimension: "explanation",
            kind: solved && solved.hints > 0 ? "assisted" : "independent",
            quote: text,
            sessionId: sessionId.current,
          },
          "provisional",
          outcome,
        );
        dispatch({ type: "growth", event });
        broadcastGrowth(event);
      }
      await say(reply);
      if (outcome) await say("Want another problem, or shall we wrap up?");
      return;
    }
    if (pending === "approach" && round.problem) {
      setPending(null);
      const finalHint = round.problem.hints[round.problem.hints.length - 1] ?? "";
      const judged = judgeAgainstRubric(text, [finalHint]);
      await say(
        judged.outcome === "demonstrated"
          ? "That's a solid plan. Go ahead and code it; run the examples whenever you like."
          : judged.outcome === "partial"
            ? "Reasonable start. Code it up and let the examples tell you what's missing."
            : "Okay, try it. If you get stuck, think about what you need to look up quickly.",
      );
      return;
    }
    if (RUN_TESTS.test(text)) {
      await round.runTests();
      return;
    }
    if (WANT_HINT.test(text)) {
      await round.hint();
      return;
    }
    if (NEXT_PROBLEM.test(text)) {
      setOpening(true);
      await advance();
      return;
    }
    await say(
      text.includes("?")
        ? "Good question. In an interview, state your assumption out loud and keep going; I'll stop you if it's wrong."
        : pick([
            "Mm-hm, keep going.",
            "Okay, makes sense.",
            "Sounds reasonable. Try it.",
            "Go on.",
          ]),
    );
  }

  const status =
    phase === "live"
      ? voice.speaking
        ? "Arjuna is speaking"
        : round.testing
          ? "Running your tests"
          : "Listening"
      : "Arjuna · Technical interviewer";

  return (
    <>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-glow">Technical interview</p>
          <h1 className="mt-1 text-2xl font-semibold sm:text-3xl">Interview with Arjuna</h1>
        </div>
        <div className="flex items-center gap-2 text-xs text-foreground/60">
          <VoiceToggle />
          <span
            className={`rounded-full px-2.5 py-1 ring-1 ${live.connected && phase !== "setup" ? "text-moss ring-moss/40" : "ring-white/15"}`}
          >
            {live.connected && phase !== "setup" ? "Live garden updates on" : "Live updates idle"}
          </span>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div className="flex flex-col gap-3">
          <CoachPortrait character="arjuna" driver={voice.lipSync} status={status} />

          {phase !== "live" && (
            <fieldset className="glass rounded-2xl p-4">
              <legend className="px-1 text-xs text-foreground/60">Language for coding</legend>
              <div className="flex flex-wrap gap-4 text-sm">
                {RUNNABLE_LANGUAGES.map((l) => (
                  <label key={l} className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="language"
                      value={l}
                      checked={language === l}
                      onChange={() => setLanguage(l)}
                    />
                    {RUNNABLE_LABELS[l]}
                  </label>
                ))}
              </div>
              <div className="mt-3">
                <PrimaryButton onClick={() => void begin()} disabled={opening}>
                  {phase === "ended" ? "Start again" : "Start interview"}
                </PrimaryButton>
              </div>
            </fieldset>
          )}

          {phase === "live" && (
            <div className="flex flex-wrap gap-2">
              <PrimaryButton tone="ember" onClick={() => void finish()}>
                End interview
              </PrimaryButton>
              <SecondaryButton
                onClick={() => void round.hint()}
                disabled={opening || !round.problem}
              >
                Ask for a hint
              </SecondaryButton>
              <SecondaryButton onClick={() => void nextProblem()} disabled={opening}>
                Next problem
              </SecondaryButton>
            </div>
          )}

          <Transcript turns={turns} empty="Arjuna's questions and your think-aloud appear here." />
          {phase === "live" && (
            <AnswerBox
              value={draft}
              onChange={setDraft}
              onSubmit={(text) => void submit(text)}
              disabled={opening}
              placeholder={
                pending === "approach"
                  ? "Your approach, in a sentence or two…"
                  : round.askedComplexity
                    ? "Time and space complexity…"
                    : "Think out loud, ask a question, or say “run the tests”…"
              }
            />
          )}
        </div>

        <div className="flex min-w-0 flex-col gap-3">
          {phase === "setup" && <PlanCard plan={plan} />}
          {phase === "live" &&
            (round.workbench ?? (
              <p className="glass rounded-2xl p-5 text-sm text-foreground/70">
                The editor opens when Arjuna gives you a problem.
              </p>
            ))}
          {phase === "ended" && result && (
            <SessionSummary
              title="Technical interview with Arjuna"
              earned={result.earned}
              saved={result.saved}
              notes={[
                "Passing tests shows behaviour on the tested cases; explaining your solution is what shows understanding.",
              ]}
              onAgain={() => setPhase("setup")}
              againLabel="Interview again"
            />
          )}
          <EvidenceTicker entries={stage.ticker} />
        </div>
      </div>
    </>
  );
}
