"use client";

import type {
  AgentRun,
  Character,
  GardenDataset,
  LiveGrowthEvent,
  RunnableLanguage,
} from "@sg/contracts";
import { RUNNABLE_LANGUAGES } from "@sg/contracts";
import Link from "next/link";
import { useCallback, useMemo, useReducer, useRef, useState } from "react";

import { ErrorBanner, StageHeader } from "@/components/session/stage-chrome";
import { EvidenceTicker, QuestionCardView } from "@/components/session/stage-parts";
import { RUNNABLE_LABELS } from "@/lib/arjuna/language";
import { useBank, type Bank, type BankProblem } from "@/lib/practice/bank";
import { pick } from "@/lib/practice/coach-lines";
import {
  recordPractice,
  toLiveEvent,
  usePracticeDataset,
  type EvidenceDraft,
} from "@/lib/practice/dataset";
import { broadcastGrowth } from "@/lib/practice/live";
import { selectProblem } from "@/lib/practice/problems";
import {
  analyseStar,
  answersProbe,
  joinList,
  type ProbeKey,
  type StarReport,
} from "@/lib/practice/scoring";
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
  SessionSummary,
  Transcript,
  VoiceToggle,
  useTurnLog,
  type EarnedItem,
} from "./conversation";

type Mode = "hr" | "panel";

interface Question {
  competency: string;
  prompt: string;
}

interface Answer {
  question: Question;
  text: string;
  report: StarReport;
  followUp: string | null;
  followUpText: string | null;
  /** Whether the follow-up gave what the probe asked for. */
  followUpAnswered: boolean;
}

const RUN_TESTS = /\b(run|try|check)\b.*\btests?\b|\bsubmit\b/i;

/** Vidura's next competencies, continuing the rotation from earlier interviews in this browser. */
function questionsFor(bank: Bank, dataset: GardenDataset, count: number, focus: string | null) {
  const rotation = bank.behavioral.rotation;
  const asked = readRecords().sessions.filter((s) => s.character === "vidura").length;
  const inGarden = new Set(dataset.plants.map((p) => p.key));
  const rotated = rotation.map((_, i) => rotation[(asked * count + i) % rotation.length]!);
  // Competencies with a plant in the garden first, so the evidence lands where it was asked.
  const order = [
    ...rotated.filter((k) => inGarden.has(k)),
    ...rotated.filter((k) => !inGarden.has(k)),
  ];
  const keys =
    focus && rotation.includes(focus) ? [focus, ...order.filter((k) => k !== focus)] : order;
  return keys.slice(0, count).map((competency, i): Question => {
    const prompts = bank.behavioral.bank[competency] ?? [];
    const prompt =
      prompts[(asked + i) % Math.max(1, prompts.length)] ??
      `Tell me about a time that shows ${competency.split(".")[1]?.replaceAll("_", " ")}.`;
    return { competency: inGarden.has(competency) ? competency : "behavioral.star_method", prompt };
  });
}

function feedbackFor(
  report: StarReport,
  probes: Record<string, string>,
): { line: string; probe: string } {
  const praise = report.strengths.length
    ? `${pick(["Thanks.", "Good.", "Okay."])} I liked that ${joinList(report.strengths.slice(0, 2))}.`
    : "Thanks for that.";
  const advice: Record<ProbeKey, string> = {
    result: "The story needs an ending, ideally with a number.",
    ownership: "I want to hear more about what you did yourself.",
    structure: "Set the scene a little before the actions.",
    specificity: "Concrete details would make it land.",
    conciseness: "It ran long; lead with the point.",
    reflection: "Strong structure.",
  };
  return {
    line: `${praise} ${advice[report.probe]}`,
    probe: probes[report.probe] ?? "What would you do differently next time?",
  };
}

export function ViduraInterview({ mode }: { mode: Mode }) {
  const dataset = usePracticeDataset();
  const { bank, error } = useBank();
  return (
    <main className="mx-auto flex w-full max-w-[1200px] flex-1 flex-col gap-4 px-4 pb-16 pt-24 sm:px-6">
      {error ? (
        <ErrorBanner message={error} />
      ) : bank ? (
        <InterviewStage bank={bank} dataset={dataset} mode={mode} />
      ) : (
        <LoadingPanel label="Your interviewers are getting ready…" />
      )}
    </main>
  );
}

function InterviewStage({
  bank,
  dataset,
  mode,
}: {
  bank: Bank;
  dataset: GardenDataset;
  mode: Mode;
}) {
  const panel = mode === "panel";
  const vidura = useCoachVoice("vidura");
  const arjuna = useCoachVoice("arjuna");
  const [turns, addTurn, clearTurns] = useTurnLog();
  const [stage, dispatch] = useReducer(stageReducer, INITIAL_STAGE);
  const [phase, setPhase] = useState<"setup" | "live" | "ended">("setup");
  const [speaker, setSpeaker] = useState<Character>("vidura");
  const [draft, setDraft] = useState("");
  // The learner may answer as soon as a question is on screen, even mid-sentence.
  const [awaiting, setAwaiting] = useState(false);
  const [language, setLanguage] = useState<RunnableLanguage>("python");
  const [step, setStep] = useState<{ kind: "answer" | "followup" | "coding"; index: number }>({
    kind: "answer",
    index: 0,
  });
  const [answers, setAnswersState] = useState<Answer[]>([]);
  // Mirrored in a ref: `finish` runs right after the last update, before a re-render.
  const answersRef = useRef<Answer[]>([]);
  const setAnswers = useCallback((change: (prev: Answer[]) => Answer[]) => {
    answersRef.current = change(answersRef.current);
    setAnswersState(answersRef.current);
  }, []);
  const [result, setResult] = useState<{ earned: EarnedItem[]; saved: boolean } | null>(null);
  const questions = useRef<Question[]>([]);
  const startedAt = useRef(0);
  const sessionId = useRef("");
  const active = useRef(false);
  // A newer turn (an answer that interrupts) makes an older flow stop at its next await.
  const flow = useRef(0);
  const startFlow = () => {
    const id = ++flow.current;
    return () => active.current && flow.current === id;
  };
  const titleOf = useMemo(
    () => new Map(dataset.plants.map((p) => [p.key, p.title])),
    [dataset.plants],
  );

  const viduraSay = vidura.say;
  const arjunaSay = arjuna.say;
  const viduraSilence = vidura.silence;
  const arjunaSilence = arjuna.silence;
  const silence = useCallback(() => {
    viduraSilence();
    arjunaSilence();
  }, [viduraSilence, arjunaSilence]);
  const say = useCallback(
    async (who: Character, text: string) => {
      setSpeaker(who);
      addTurn(who, text);
      await (who === "arjuna" ? arjunaSay : viduraSay)(text);
    },
    [addTurn, arjunaSay, viduraSay],
  );
  const arjunaSays = useCallback((text: string) => say("arjuna", text), [say]);
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
  const round = useCodingRound({ say: arjunaSays, onRun });
  const live = useLiveGrowth({
    enabled: phase !== "setup",
    onEvent: useCallback((e: LiveGrowthEvent) => dispatch({ type: "growth", event: e }), []),
  });

  function showQuestion(q: Question, index: number) {
    dispatch({
      type: "card",
      now: Date.now(),
      card: {
        questionId: `behavioral:${q.competency}:${index}`,
        title: titleOf.get(q.competency) ?? "Behavioural question",
        body: q.prompt,
        kind: "behavioral",
        conceptId: q.competency,
      },
    });
  }

  async function begin() {
    const focus = new URLSearchParams(window.location.search).get("concept");
    questions.current = questionsFor(bank, dataset, panel ? 1 : 3, focus);
    sessionId.current = newId("ses");
    startedAt.current = Date.now();
    active.current = true;
    round.reset();
    clearTurns();
    dispatch({ type: "reset" });
    setAnswers(() => []);
    setResult(null);
    setStep({ kind: "answer", index: 0 });
    setPhase("live");
    setAwaiting(false);
    const current = startFlow();
    await say(
      "vidura",
      panel
        ? "Welcome. I'm Vidura, and this is Arjuna. I'll start with one question about your experience, then Arjuna has a technical problem for you."
        : `Welcome, I'm Vidura. I'll ask you ${questions.current.length} questions about your experience. Take your time, and tell me what you did, not just the team.`,
    );
    if (!current()) return;
    const first = questions.current[0]!;
    showQuestion(first, 0);
    setAwaiting(true);
    await say("vidura", first.prompt);
  }

  async function startCoding() {
    const easy = bank.problems.filter((p) => p.difficulty <= 2).map((p) => p.concept_id);
    const { problem } = selectProblem(bank, easy[Math.floor(Math.random() * easy.length)] ?? null);
    dispatch({ type: "dismiss", what: "card" });
    setStep({ kind: "coding", index: 0 });
    round.open(problem, language);
    setAwaiting(true);
    await say(
      "arjuna",
      `Thanks, Vidura. Here's a problem for you: ${problem.title}. Talk me through your idea, then code it, and tell me when to run the tests.`,
    );
  }

  async function finish() {
    if (!active.current) return;
    active.current = false;
    flow.current += 1;
    setAwaiting(false);
    silence();
    const drafts: EvidenceDraft[] = [];
    for (const a of answersRef.current) {
      if (a.report.outcome !== "not_demonstrated")
        drafts.push({
          plantKey: a.question.competency,
          dimension: "explanation",
          kind: "independent",
          outcome: a.report.outcome,
          quote: a.text,
          source: "transcript",
          rationale: `STAR: ${a.report.parts} of 4 parts (${[
            a.report.situation && "situation",
            a.report.task && "task",
            a.report.action && "actions",
            a.report.result && "result",
          ]
            .filter(Boolean)
            .join(", ")})${a.report.specific ? ", with concrete detail" : ""}.`,
          confidence: 0.7,
        });
      if (a.followUpAnswered && a.followUpText)
        drafts.push({
          plantKey: a.question.competency,
          dimension: "transfer",
          kind: "independent",
          outcome: "demonstrated",
          quote: a.followUpText,
          source: "transcript",
          rationale: "Adapted the story to a follow-up probe.",
          confidence: 0.65,
        });
    }
    drafts.push(...round.evidence());
    const recorded = recordPractice({
      character: "vidura",
      title: panel
        ? "Panel interview: Vidura and Arjuna"
        : `Vidura: ${titleOf.get(questions.current[0]?.competency ?? "") ?? "HR interview"}`,
      startedAt: startedAt.current,
      endedAt: Date.now(),
      evidence: drafts,
    });
    setResult({
      saved: recorded.saved,
      earned: drafts.map((d) => ({
        plantTitle: titleOf.get(d.plantKey) ?? d.plantKey,
        dimension: d.dimension,
        outcome: d.outcome,
        assisted: d.kind === "assisted",
        quote: d.source === "tests" ? d.rationale : d.quote,
      })),
    });
    dispatch({ type: "dismiss", what: "card" });
    setPhase("ended");
    await say(
      "vidura",
      "That's the end of our interview. Thank you. Your feedback is below, and what you showed is in your garden.",
    );
  }

  async function submit(text: string) {
    if (!awaiting || phase !== "live") return;
    const current = startFlow();
    setAwaiting(false);
    silence();
    setDraft("");
    addTurn("you", text);
    try {
      if (step.kind === "coding") {
        if (round.askedComplexity) {
          const { reply } = round.answerComplexity(text);
          await say("arjuna", reply);
          if (!current()) return;
          await say(
            "vidura",
            "Thank you both. Whenever you're ready, end the interview for your feedback.",
          );
          return;
        }
        if (RUN_TESTS.test(text)) {
          await round.runTests();
          return;
        }
        setAwaiting(true);
        await say(
          "arjuna",
          text.includes("?")
            ? "State your assumption and keep going."
            : pick(["Mm-hm.", "Okay, go on.", "Sounds good, try it."]),
        );
        return;
      }

      const question = questions.current[step.index]!;
      if (step.kind === "answer") {
        const report = analyseStar(text);
        const { line, probe } = feedbackFor(report, bank.behavioral.probes);
        const answer: Answer = {
          question,
          text,
          report,
          followUp: probe,
          followUpText: null,
          followUpAnswered: false,
        };
        setAnswers((prev) => [...prev, answer]);
        if (report.outcome !== "not_demonstrated") {
          const event = toLiveEvent(
            {
              plantKey: question.competency,
              dimension: "explanation",
              kind: "independent",
              quote: text,
              sessionId: sessionId.current,
            },
            "provisional",
            report.outcome,
          );
          dispatch({ type: "growth", event });
          broadcastGrowth(event);
        }
        setStep({ kind: "followup", index: step.index });
        setAwaiting(true);
        await say("vidura", `${line} ${probe}`);
        return;
      }

      // Follow-up answered: note it, then the next question (or Arjuna, or the end).
      const last = answersRef.current[answersRef.current.length - 1];
      const answered = last ? answersProbe(last.report.probe, text) : false;
      setAnswers((prev) =>
        prev.map((a, i) =>
          i === prev.length - 1 ? { ...a, followUpText: text, followUpAnswered: answered } : a,
        ),
      );
      if (answered && last) {
        const event = toLiveEvent(
          {
            plantKey: last.question.competency,
            dimension: "transfer",
            kind: "independent",
            quote: text,
            sessionId: sessionId.current,
          },
          "provisional",
        );
        dispatch({ type: "growth", event });
        broadcastGrowth(event);
      }
      const next = step.index + 1;
      if (next < questions.current.length) {
        await say(
          "vidura",
          pick([
            "Thank you. Next question.",
            "Good, thanks. Let's move on.",
            "Understood. Another one.",
          ]),
        );
        if (!current()) return;
        const q = questions.current[next]!;
        showQuestion(q, next);
        setStep({ kind: "answer", index: next });
        setAwaiting(true);
        await say("vidura", q.prompt);
      } else if (panel) {
        await say("vidura", "Thank you. Arjuna, over to you.");
        if (current()) await startCoding();
      } else {
        await finish();
      }
    } finally {
      // In the coding round the learner can always talk; elsewhere the next question re-opens.
      if (current() && step.kind === "coding") setAwaiting(true);
    }
  }

  const title = panel ? "Panel interview" : "HR interview with Vidura";
  const statusFor = (who: Character) =>
    phase === "live" && speaker === who && (who === "arjuna" ? arjuna.speaking : vidura.speaking)
      ? `${who === "arjuna" ? "Arjuna" : "Vidura"} is speaking`
      : who === "arjuna"
        ? "Arjuna"
        : "Vidura";

  return (
    <>
      <StageHeader
        eyebrow="Interview practice"
        title={title}
        isMock={false}
        liveConnected={live.connected && phase !== "setup"}
        extra={<VoiceToggle />}
      />

      <div
        className="flex h-72 gap-3 sm:h-80"
        aria-label={panel ? "Interview panel" : "Interviewer"}
      >
        <div
          className="min-w-0 transition-[flex-grow] duration-700"
          style={{ flexGrow: panel && speaker === "arjuna" ? 1 : 1.6, flexBasis: 0 }}
        >
          <CoachPortrait
            character="vidura"
            driver={vidura.lipSync}
            status={statusFor("vidura")}
            emphasis={!panel || speaker === "vidura"}
            className="h-full"
            size={panel ? 140 : 200}
          />
        </div>
        {panel && (
          <div
            className="min-w-0 transition-[flex-grow] duration-700"
            style={{ flexGrow: speaker === "arjuna" ? 1.6 : 1, flexBasis: 0 }}
          >
            <CoachPortrait
              character="arjuna"
              driver={arjuna.lipSync}
              status={statusFor("arjuna")}
              emphasis={speaker === "arjuna"}
              className="h-full"
              size={panel ? 140 : 200}
            />
          </div>
        )}
      </div>

      {phase !== "live" && (
        <section className="glass flex flex-col gap-3 rounded-2xl p-4">
          <p className="text-sm text-foreground/75">
            {panel
              ? "One behavioural question from Vidura, then a coding problem from Arjuna. Answer out loud or by typing."
              : "Three behavioural questions. Vidura listens for structure (situation, task, actions, result), specifics and your own part in the story."}
          </p>
          {panel && (
            <fieldset className="flex flex-wrap gap-4 text-sm">
              <legend className="mb-1.5 text-foreground/70">Language for the coding part</legend>
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
            </fieldset>
          )}
          <div className="flex flex-wrap gap-2">
            <PrimaryButton onClick={() => void begin()}>
              {phase === "ended" ? "Start again" : "Start interview"}
            </PrimaryButton>
            <Link
              href={{ pathname: "/interview" }}
              className="rounded-xl border border-white/15 px-4 py-2.5 text-sm outline-none hover:border-white/30 focus-visible:ring-2 focus-visible:ring-glow"
            >
              Choose another interview
            </Link>
          </div>
        </section>
      )}

      {phase === "live" && (
        <div className="flex flex-wrap gap-2">
          <PrimaryButton tone="ember" onClick={() => void finish()}>
            End interview
          </PrimaryButton>
        </div>
      )}

      {stage.card && phase === "live" && (
        <QuestionCardView
          card={stage.card}
          onClose={() => dispatch({ type: "dismiss", what: "card" })}
        />
      )}
      {phase === "live" && step.kind === "coding" && round.workbench}

      <Transcript turns={turns} empty="The interview transcript appears here." />
      {phase === "live" && (
        <AnswerBox
          value={draft}
          onChange={setDraft}
          onSubmit={(text) => void submit(text)}
          disabled={!awaiting}
          placeholder={
            step.kind === "coding"
              ? round.askedComplexity
                ? "Time and space complexity…"
                : "Think out loud, or say “run the tests”…"
              : step.kind === "followup"
                ? "Answer the follow-up…"
                : "Your story: situation, task, what you did, and the result…"
          }
        />
      )}

      {phase === "ended" && answers.length > 0 && (
        <section aria-label="Feedback" className="glass rounded-2xl p-5">
          <h2 className="text-lg font-semibold">How your answers were structured</h2>
          <ul className="mt-3 flex flex-col gap-3">
            {answers.map((a, i) => (
              <li key={i} className="rounded-xl bg-white/5 p-3 text-sm">
                <p className="font-medium">{a.question.prompt}</p>
                <p className="mt-2 flex flex-wrap gap-2 text-xs">
                  {(
                    [
                      ["Situation", a.report.situation],
                      ["Task", a.report.task],
                      ["Actions", a.report.action],
                      ["Result", a.report.result],
                      ["Specific", a.report.specific],
                      ["Your part", a.report.ownership],
                      ["Reflection", a.report.reflection],
                    ] as const
                  ).map(([label, ok]) => (
                    <span
                      key={label}
                      className={`rounded-full px-2 py-0.5 ring-1 ${ok ? "text-moss ring-moss/40" : "text-foreground/50 ring-white/15"}`}
                    >
                      {ok ? "✓" : "·"} {label}
                    </span>
                  ))}
                  <span className="rounded-full px-2 py-0.5 text-foreground/50 ring-1 ring-white/15">
                    {a.report.words} words
                  </span>
                </p>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs text-foreground/50">
            Feedback is about how the story was told, never about you as a person.
          </p>
        </section>
      )}
      {phase === "ended" && result && (
        <SessionSummary
          title={title}
          earned={result.earned}
          saved={result.saved}
          onAgain={() => setPhase("setup")}
          againLabel="Interview again"
        />
      )}
      <EvidenceTicker entries={stage.ticker} />
    </>
  );
}

export function InterviewChooser() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 pb-16 pt-28 sm:px-6">
      <header>
        <p className="text-xs uppercase tracking-[0.3em] text-glow">Interview practice</p>
        <h1 className="mt-1 text-3xl font-semibold">Choose your interview</h1>
      </header>
      <div className="grid gap-4 sm:grid-cols-2">
        <Link
          href={{ pathname: "/interview", query: { mode: "hr" } }}
          className="glass rounded-2xl border border-white/10 p-5 outline-none hover:border-glow/40 focus-visible:ring-2 focus-visible:ring-glow"
        >
          <h2 className="text-lg font-semibold">HR interview with Vidura</h2>
          <p className="mt-2 text-sm text-foreground/70">
            Three behavioural questions about your experience, with feedback on structure,
            specificity, ownership and conciseness.
          </p>
        </Link>
        <Link
          href={{ pathname: "/interview", query: { mode: "panel" } }}
          className="glass rounded-2xl border border-white/10 p-5 outline-none hover:border-glow/40 focus-visible:ring-2 focus-visible:ring-glow"
        >
          <h2 className="text-lg font-semibold">Panel with Vidura and Arjuna</h2>
          <p className="mt-2 text-sm text-foreground/70">
            One behavioural question, then a coding problem, with both interviewers on stage.
          </p>
        </Link>
        <Link
          href="/interview/technical"
          className="glass rounded-2xl border border-white/10 p-5 outline-none hover:border-glow/40 focus-visible:ring-2 focus-visible:ring-glow sm:col-span-2"
        >
          <h2 className="text-lg font-semibold">Technical interview with Arjuna</h2>
          <p className="mt-2 text-sm text-foreground/70">
            Live coding in Python, JavaScript or TypeScript, with hidden tests that really run.
          </p>
        </Link>
      </div>
    </main>
  );
}
