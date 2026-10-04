"use client";

import type { Dimension, GardenDataset, LiveGrowthEvent } from "@sg/contracts";
import { useCallback, useMemo, useReducer, useRef, useState } from "react";

import { GardenSceneSlot } from "@/components/garden/garden-scene-slot";
import { useGardenDashboard } from "@/components/garden/use-garden-dashboard";
import { ErrorBanner, StageHeader } from "@/components/session/stage-chrome";
import { EvidenceTicker, QuestionCardView, TeachBackPanel } from "@/components/session/stage-parts";
import { DEFAULT_STATE } from "@/lib/garden/state";
import { conceptByKey, useBank, type Bank, type BankConcept } from "@/lib/practice/bank";
import {
  coveredLine,
  lowerFirst,
  pick,
  questionFor,
  sentence,
  todoLine,
} from "@/lib/practice/coach-lines";
import {
  recordPractice,
  toLiveEvent,
  usePracticeDataset,
  type EvidenceDraft,
} from "@/lib/practice/dataset";
import { broadcastGrowth } from "@/lib/practice/live";
import { judgeAgainstRubric, judgeCorrection, wordCount } from "@/lib/practice/scoring";
import { useCoachVoice } from "@/lib/practice/speech";
import { newId } from "@/lib/practice/store";
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

type Mode = "concept_exam" | "teach_back";

interface Step {
  id: string;
  kind: "rubric" | "correction";
  cardKind: "concept_check" | "cross_question" | "teach_back";
  title: string;
  prompt: string;
  criteria: string[];
  dimension: Dimension;
  misconception?: string;
}

const trimDot = (s: string) => s.trim().replace(/[.]+$/, "");

/** The questions of one session, built from the concept's rubric like `sg_api.drona.questions`. */
function planSteps(concept: BankConcept, mode: Mode): Step[] {
  const explanation = concept.rubric.explanation ?? [];
  const application = concept.rubric.application ?? [];
  const transfer = concept.rubric.transfer ?? [];
  const misconceptions = concept.rubric.misconceptions ?? [];
  const steps: Step[] = [];
  if (mode === "teach_back") {
    const teach = concept.questions.teach_back?.[0];
    steps.push({
      id: teach?.id ?? `teach_back:${concept.key}:0`,
      kind: "rubric",
      cardKind: "teach_back",
      title: "Teach me",
      prompt:
        teach?.prompt ??
        `Pretend I'm a first-year student who has never seen ${concept.title}. Teach it to me in your own words.`,
      criteria: explanation,
      dimension: "explanation",
    });
    if (misconceptions[0])
      steps.push({
        id: `teach_back:${concept.key}:1`,
        kind: "correction",
        cardKind: "teach_back",
        title: "Your student is confused",
        prompt: `Hmm, wait. So ${lowerFirst(trimDot(misconceptions[0]))}? That's what I always thought.`,
        criteria: explanation,
        dimension: "explanation",
        misconception: misconceptions[0],
      });
    const use = application[0] ?? transfer[0];
    if (use)
      steps.push({
        id: `teach_back:${concept.key}:2`,
        kind: "rubric",
        cardKind: "teach_back",
        title: "When would I use it?",
        prompt: `Okay, I think I get it. So when would I actually use ${concept.title.toLowerCase()}? Give me a real example.`,
        criteria: [use],
        dimension: application[0] ? "application" : "transfer",
      });
    return steps;
  }

  const first = concept.questions.concept_check?.[0];
  steps.push({
    id: first?.id ?? `concept_check:${concept.key}:0`,
    kind: "rubric",
    cardKind: "concept_check",
    title: concept.title,
    prompt: first?.prompt ?? `In your own words, what is ${concept.title}, and why does it work?`,
    criteria: first?.hints.length ? first.hints : explanation,
    dimension: "explanation",
  });
  const cross = concept.questions.cross_question ?? [];
  const appCriterion = application[0];
  const transferCriterion = transfer[0];
  const stretch = appCriterion ?? transferCriterion;
  if (stretch) {
    const asked = cross.find((q) => q.hints[0] === stretch);
    steps.push({
      id: asked?.id ?? `cross_question:${concept.key}:0`,
      kind: "rubric",
      cardKind: "cross_question",
      title: appCriterion ? "Apply it" : "Stretch it",
      prompt:
        questionFor(stretch) ?? asked?.prompt ?? `Where would you use ${concept.title}, and why?`,
      criteria: [stretch],
      dimension: appCriterion ? "application" : "transfer",
    });
  }
  const myth = cross.find((q) => q.hints[0]?.startsWith("Common misconception: "));
  if (myth)
    steps.push({
      id: myth.id,
      kind: "correction",
      cardKind: "cross_question",
      title: "True or false?",
      prompt: myth.prompt,
      criteria: explanation,
      dimension: "explanation",
      misconception: myth.hints[0]!.replace("Common misconception: ", ""),
    });
  return steps;
}

function practicable(bank: Bank, dataset: GardenDataset) {
  const inGarden = new Set(dataset.plants.map((p) => p.key));
  return bank.concepts.filter((c) => inGarden.has(c.key) && c.grove !== "behavioral");
}

function initialConcept(dataset: GardenDataset, options: BankConcept[]): string {
  const params = new URLSearchParams(window.location.search);
  const keys = new Set(options.map((c) => c.key));
  const fromUrl = params.get("concept") ?? params.get("focus")?.split(":")[1];
  if (fromUrl && keys.has(fromUrl)) return fromUrl;
  const suggested = dataset.nextBest.find((n) => n.character === "drona" && keys.has(n.plantKey));
  if (suggested) return suggested.plantKey;
  return options[0]?.key ?? "";
}

export function DronaSession() {
  const dataset = usePracticeDataset();
  const { bank, error } = useBank();
  return (
    <main className="mx-auto flex w-full max-w-[1400px] flex-1 flex-col gap-4 px-4 pb-16 pt-24 sm:px-6">
      {error ? (
        <ErrorBanner message={error} />
      ) : bank ? (
        <DronaStage bank={bank} dataset={dataset} />
      ) : (
        <LoadingPanel label="Drona is getting ready…" />
      )}
    </main>
  );
}

function DronaStage({ bank, dataset }: { bank: Bank; dataset: GardenDataset }) {
  const options = useMemo(() => practicable(bank, dataset), [bank, dataset]);
  const [conceptKey, setConceptKey] = useState(() => initialConcept(dataset, options));
  const [mode, setMode] = useState<Mode>(() =>
    new URLSearchParams(window.location.search).get("mode") === "teach_back"
      ? "teach_back"
      : "concept_exam",
  );
  const concept = conceptByKey(bank, conceptKey) ?? options[0];
  const garden = useGardenDashboard(dataset, {
    ...DEFAULT_STATE,
    focus: conceptKey ? { level: "plant", plantKey: conceptKey } : { level: "garden" },
  });
  const voice = useCoachVoice("drona");
  const [stage, dispatch] = useReducer(stageReducer, INITIAL_STAGE);
  const [turns, addTurn, clearTurns] = useTurnLog();
  const [phase, setPhase] = useState<"setup" | "live" | "ended">("setup");
  const [steps, setSteps] = useState<Step[]>([]);
  const [index, setIndex] = useState(0);
  const [draft, setDraft] = useState("");
  // The learner may answer once a question is on screen, even while Drona is still reading it.
  const [awaiting, setAwaiting] = useState(false);
  const [hints, setHints] = useState(0);
  const [nudged, setNudged] = useState(false);
  const [result, setResult] = useState<{ earned: EarnedItem[]; saved: boolean } | null>(null);
  const evidence = useRef<EvidenceDraft[]>([]);
  const startedAt = useRef(0);
  const sessionId = useRef("");
  const active = useRef(false);
  // Each turn of the conversation is a flow; a newer one (an answer that interrupts Drona)
  // makes the older one stop at its next await.
  const flow = useRef(0);
  const startFlow = () => {
    const id = ++flow.current;
    return () => active.current && flow.current === id;
  };

  const live = useLiveGrowth({
    enabled: phase !== "setup",
    onEvent: useCallback((e: LiveGrowthEvent) => dispatch({ type: "growth", event: e }), []),
  });

  if (!concept) {
    return <ErrorBanner message="No concepts are available to practise yet." />;
  }

  const title = mode === "teach_back" ? "Teach-back with Drona" : "Concept practice with Drona";
  const step = steps[index];

  async function ask(next: Step) {
    dispatch({
      type: "card",
      now: Date.now(),
      card: {
        questionId: next.id,
        title: next.title,
        body: next.prompt,
        kind: next.cardKind,
        conceptId: concept!.key,
      },
    });
    addTurn("drona", next.prompt);
    setAwaiting(true);
    await voice.say(next.prompt);
  }

  async function begin() {
    const planned = planSteps(concept!, mode);
    evidence.current = [];
    sessionId.current = newId("ses");
    startedAt.current = Date.now();
    active.current = true;
    dispatch({ type: "reset" });
    clearTurns();
    setResult(null);
    setSteps(planned);
    setIndex(0);
    setHints(0);
    setNudged(false);
    setDraft("");
    setPhase("live");
    setAwaiting(false);
    const current = startFlow();
    garden.actions.focusOn({ level: "plant", plantKey: concept!.key });
    const intro =
      mode === "teach_back"
        ? `Today you are the teacher. I'll play a first-year student who has never heard of ${concept!.title}.`
        : `Let's practise ${concept!.title}. Answer in your own words, out loud or typed, and I'll tell you what you covered.`;
    addTurn("drona", intro);
    await voice.say(intro);
    if (current()) await ask(planned[0]!);
  }

  async function finish() {
    if (!active.current) return;
    active.current = false;
    flow.current += 1;
    setAwaiting(false);
    voice.silence();
    const grown = evidence.current.length;
    const outro = grown
      ? `That's our session. ${grown} ${grown === 1 ? "answer" : "answers"} grew your ${concept!.title} plant, and it's saved in your garden.`
      : "Let's stop here. Nothing grew this time, and that's fine: come back and try again.";
    addTurn("drona", outro);
    const recorded = recordPractice({
      character: "drona",
      title: `Drona: ${concept!.title}${mode === "teach_back" ? " (teach-back)" : ""}`,
      startedAt: startedAt.current,
      endedAt: Date.now(),
      evidence: evidence.current,
    });
    setResult({
      saved: recorded.saved,
      earned: evidence.current.map((d) => ({
        plantTitle: concept!.title,
        dimension: d.dimension,
        outcome: d.outcome,
        assisted: d.kind === "assisted",
        quote: d.quote,
      })),
    });
    dispatch({ type: "dismiss", what: "card" });
    dispatch({ type: "endTeachBack" });
    setPhase("ended");
    await voice.say(outro);
  }

  async function submit(text: string) {
    if (!step || !awaiting || phase !== "live") return;
    const current = startFlow();
    setAwaiting(false);
    voice.silence();
    setDraft("");
    addTurn("you", text);
    if (step.kind === "rubric" && wordCount(text) < 6 && !nudged) {
      setNudged(true);
      const line = "Say a little more. Explain it as if I have never seen it before.";
      addTurn("drona", line);
      setAwaiting(true);
      await voice.say(line);
      return;
    }

    const assisted = hints > 0;
    let outcome: "demonstrated" | "partial" | "not_demonstrated";
    let confidence: number;
    let rationale: string;
    let line: string;
    if (step.kind === "correction") {
      const judged = judgeCorrection(text, step.misconception!, step.criteria);
      outcome = judged.outcome;
      confidence = judged.confidence;
      rationale = judged.disagrees
        ? `Rejected the common misconception (“${trimDot(step.misconception!)}”) and explained why.`
        : `Agreed with a common misconception: “${trimDot(step.misconception!)}”.`;
      line =
        outcome === "demonstrated"
          ? `${pick(["Exactly.", "Right.", "Good catch."])} That claim is a common misconception, and you explained why.`
          : outcome === "partial"
            ? "Right, it isn't true. Next time say why it fails, in one sentence."
            : `Careful: that is a common misconception. ${sentence(step.criteria[0] ?? "")}`;
    } else {
      const judged = judgeAgainstRubric(text, step.criteria);
      outcome = judged.outcome;
      confidence = judged.confidence;
      const covered = judged.covered.map((c) => c.criterion);
      const missed = judged.missed.map((c) => c.criterion);
      rationale = covered.length
        ? `Covered: ${covered.map((c) => trimDot(c)).join("; ")}.`
        : `Partly covered: ${trimDot(step.criteria[0] ?? "")}.`;
      if (outcome === "demonstrated") {
        line = `${pick(["Good.", "Yes.", "Nicely put."])} ${sentence(coveredLine(covered[0]!))}${
          missed[0] ? ` To go further, ${todoLine(missed[0])}.` : ""
        }`;
      } else if (outcome === "partial") {
        line = `Partly there. ${covered[0] ? `${sentence(coveredLine(covered[0]))} ` : ""}What's missing: ${todoLine(missed[0] ?? step.criteria[0] ?? "")}.`;
      } else {
        line = `Not quite yet. A strong answer would ${todoLine(missed[0] ?? step.criteria[0] ?? "")}.`;
      }
    }

    if (outcome !== "not_demonstrated") {
      const item: EvidenceDraft = {
        plantKey: concept!.key,
        dimension: step.dimension,
        kind: assisted ? "assisted" : "independent",
        outcome,
        quote: text,
        source: "transcript",
        rationale,
        assistNote: assisted
          ? `Answered after ${hints} ${hints === 1 ? "hint" : "hints"} from Drona.`
          : undefined,
        confidence,
      };
      evidence.current.push(item);
      const event = toLiveEvent({ ...item, sessionId: sessionId.current }, "provisional", outcome);
      dispatch({ type: "growth", event });
      broadcastGrowth(event);
    }

    addTurn("drona", line);
    await voice.say(line);
    if (!current()) return;
    setHints(0);
    setNudged(false);
    const next = index + 1;
    if (next < steps.length) {
      setIndex(next);
      await ask(steps[next]!);
    } else {
      await finish();
    }
  }

  async function hint() {
    if (!step || !awaiting) return;
    startFlow();
    setAwaiting(false);
    voice.silence();
    const used = hints + 1;
    setHints(used);
    const criterion = step.criteria[(used - 1) % Math.max(1, step.criteria.length)] ?? "";
    const line =
      step.kind === "correction"
        ? `A nudge: is it always true? Think about this: ${lowerFirst(trimDot(criterion))}.`
        : `A hint: a strong answer would ${todoLine(criterion)}.`;
    addTurn("drona", line);
    setAwaiting(true);
    await voice.say(line);
  }

  async function skip() {
    if (!step || !awaiting) return;
    startFlow();
    setAwaiting(false);
    voice.silence();
    setHints(0);
    setNudged(false);
    const next = index + 1;
    if (next < steps.length) {
      setIndex(next);
      await ask(steps[next]!);
    } else await finish();
  }

  const status =
    phase === "live" ? (voice.speaking ? "Drona is speaking" : "Your turn") : "Drona · Teacher";
  const recentGrowth = [...live.pulseConceptIds];

  return (
    <>
      <StageHeader
        eyebrow="Voice session"
        title={title}
        subtitle={concept.title}
        isMock={false}
        liveConnected={live.connected}
        extra={<VoiceToggle />}
      />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,24rem)_minmax(0,1fr)]">
        <div className="flex flex-col gap-3">
          <CoachPortrait character="drona" driver={voice.lipSync} status={status} />

          {phase !== "live" && (
            <section
              className="glass flex flex-col gap-3 rounded-2xl p-4"
              aria-label="Session setup"
            >
              <label className="flex flex-col gap-1.5 text-sm">
                <span className="text-foreground/70">Concept</span>
                <select
                  value={concept.key}
                  onChange={(e) => {
                    setConceptKey(e.target.value);
                    garden.actions.focusOn({ level: "plant", plantKey: e.target.value });
                  }}
                  className="w-full min-w-0 rounded-lg border border-white/15 bg-night px-3 py-2 outline-none focus-visible:ring-2 focus-visible:ring-glow"
                >
                  {dataset.groves
                    .filter((g) => options.some((c) => c.grove === g.id))
                    .map((g) => (
                      <optgroup key={g.id} label={g.title}>
                        {options
                          .filter((c) => c.grove === g.id)
                          .map((c) => (
                            <option key={c.key} value={c.key}>
                              {c.title}
                            </option>
                          ))}
                      </optgroup>
                    ))}
                </select>
              </label>
              <fieldset className="flex flex-wrap gap-4 text-sm">
                <legend className="mb-1.5 text-foreground/70">Mode</legend>
                {(
                  [
                    ["concept_exam", "Concept practice"],
                    ["teach_back", "Teach-back"],
                  ] as const
                ).map(([value, label]) => (
                  <label key={value} className="flex items-center gap-2">
                    <input
                      type="radio"
                      name="mode"
                      value={value}
                      checked={mode === value}
                      onChange={() => setMode(value)}
                    />
                    {label}
                  </label>
                ))}
              </fieldset>
              <p className="text-xs text-foreground/60">{concept.summary}</p>
              <div>
                <PrimaryButton onClick={() => void begin()}>
                  {phase === "ended" ? "Start another session" : "Start session"}
                </PrimaryButton>
              </div>
            </section>
          )}

          {phase === "live" && (
            <div className="flex flex-wrap gap-2">
              <PrimaryButton tone="ember" onClick={() => void finish()}>
                End session
              </PrimaryButton>
            </div>
          )}

          <Transcript
            turns={turns}
            empty="Drona's questions and your answers appear here. Start a session when you're ready."
          />
        </div>

        <div className="flex min-w-0 flex-col gap-3">
          {stage.card && phase === "live" && (
            <QuestionCardView
              card={stage.card}
              onClose={() => dispatch({ type: "dismiss", what: "card" })}
            />
          )}
          {phase === "live" && stage.teachBack && (
            <TeachBackPanel
              startedAt={stage.teachBackStartedAt}
              heard={draft}
              onDone={() => void submit(draft.trim())}
              disabled={!awaiting || !draft.trim()}
            />
          )}
          {phase === "live" && (
            <AnswerBox
              value={draft}
              onChange={setDraft}
              onSubmit={(text) => void submit(text)}
              disabled={!awaiting}
              placeholder={
                stage.teachBack ? "Explain it to your student…" : "Your answer, in your own words…"
              }
            >
              <SecondaryButton onClick={() => void hint()} disabled={!awaiting}>
                Hint
              </SecondaryButton>
              <SecondaryButton onClick={() => void skip()} disabled={!awaiting}>
                Skip
              </SecondaryButton>
            </AnswerBox>
          )}
          {phase === "ended" && result && (
            <SessionSummary
              title={`${concept.title} with Drona`}
              earned={result.earned}
              saved={result.saved}
              notes={
                result.earned.some((e) => e.assisted)
                  ? [
                      "Answers given after a hint count as assisted: they show on the plant as ghost growth.",
                    ]
                  : []
              }
              onAgain={() => setPhase("setup")}
            />
          )}
          <GardenSceneSlot
            groves={dataset.groves}
            plants={garden.view.plants}
            focus={garden.state.focus}
            onFocusChange={garden.actions.focusOn}
            asOf={new Date(garden.view.cutoff).toISOString()}
            isTimeTravel={garden.view.isPast}
            recentGrowthPlantKeys={recentGrowth}
            evidence={garden.view.evidence}
            prerequisites={dataset.prerequisites}
            revision={dataset.growthEvents.reduce((max, g) => Math.max(max, g.revision), 0)}
            ruleVersion={dataset.freshness.rulesVersion}
          />
          <EvidenceTicker entries={stage.ticker} />
        </div>
      </div>
    </>
  );
}
