"use client";

import { ConversationProvider, useConversation } from "@elevenlabs/react";
import type {
  AgentRun,
  ArjunaPlan,
  EditorLanguage,
  LiveGrowthEvent,
  OpenEditorArgs,
  ProblemView,
  RunnableLanguage,
} from "@sg/contracts";
import { RUNNABLE_LANGUAGES } from "@sg/contracts";
import { fromAgentAlignment, useLipSync } from "@sg/three/avatar";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { bindConversation, endSession } from "@/app/(app)/session/actions";
import {
  getProblem,
  getScribeToken,
  listRuns,
  runExamples,
  saveCode,
  startArjunaSession,
} from "@/app/(app)/interview/technical/actions";
import { AvatarSlot } from "@/components/session/avatar-slot";
import { Captions, EvidenceTicker, QuestionCardView } from "@/components/session/stage-parts";
import { createCodeSync, type CodeSync } from "@/lib/arjuna/code-sync";
import { asRunnable, RUNNABLE_LABELS } from "@/lib/arjuna/language";
import { latestRunFor, mergeRuns, pollCursor } from "@/lib/arjuna/runs";
import { AlignmentClock } from "@/lib/session/alignment-clock";
import { INITIAL_STAGE, createStageTools, stageReducer } from "@/lib/session/stage";
import { useLiveGrowth } from "@/lib/session/use-live-growth";

import { PlanCard } from "./plan-card";
import { ThinkAloud } from "./think-aloud";
import { Workbench } from "./workbench";

type Phase = "idle" | "starting" | "live" | "ended" | "interrupted";

const RUN_POLL_MS = 3000;
const wallClock = () => Date.now();

export interface ArjunaStageProps {
  plan: ArjunaPlan | null;
  initialConcept?: string;
  vrmUrl?: string;
}

export function ArjunaStage(props: ArjunaStageProps) {
  return (
    <ConversationProvider>
      <Stage {...props} />
    </ConversationProvider>
  );
}

function Stage({ plan: initialPlan, initialConcept, vrmUrl }: ArjunaStageProps) {
  const lipSync = useLipSync();
  const clock = useRef(new AlignmentClock());
  const [stage, dispatch] = useReducer(stageReducer, INITIAL_STAGE);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [captions, setCaptions] = useState({ agent: "", user: "" });
  const [plan, setPlan] = useState<ArjunaPlan | null>(initialPlan);
  const [language, setLanguage] = useState<RunnableLanguage>("python");
  const [problem, setProblem] = useState<ProblemView | null>(null);
  // The code the editor opens with: the learner's draft for this problem and language, if any.
  const [initialCode, setInitialCode] = useState("");
  const [runs, setRuns] = useState<AgentRun[]>([]);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const sessionId = useRef<string | null>(null);
  const phaseRef = useRef<Phase>("idle");
  const drafts = useRef(new Map<string, string>());
  const sync = useRef<CodeSync | null>(null);
  const setPhaseBoth = useCallback((next: Phase) => {
    phaseRef.current = next;
    setPhase(next);
  }, []);

  const live = useLiveGrowth({
    enabled: phase === "live" || phase === "ended",
    onEvent: useCallback((e: LiveGrowthEvent) => dispatch({ type: "growth", event: e }), []),
  });

  // The agent opens the editor by name; loading the problem happens in the browser.
  const loadProblem = useCallback(async (args: Partial<OpenEditorArgs>): Promise<string> => {
    const language = (args.language ?? "python") as EditorLanguage;
    const result = await getProblem(String(args.problem_id ?? ""), language);
    if (!result.ok) return `The editor could not open that problem: ${result.message}`;
    setInitialCode(
      drafts.current.get(`${result.data.id}:${result.data.language}`) ?? result.data.starter_code,
    );
    setProblem(result.data);
    setLanguage(asRunnable(result.data.language));
    return `Editor opened with "${result.data.title}" in ${result.data.language}. ${
      result.data.tests_available
        ? "Tests can run."
        : "Tests do not run for this language: ask the candidate to switch to Python, JavaScript or TypeScript."
    }`;
  }, []);
  const loadProblemRef = useRef(loadProblem);
  useEffect(() => {
    loadProblemRef.current = loadProblem;
  });

  const conversationRef = useRef<{ sendContextualUpdate: (text: string) => void } | null>(null);

  const tools = useMemo(() => {
    const base = createStageTools({
      dispatch,
      now: wallClock,
      // The garden is not on screen during an interview; these tools are not given to Arjuna.
      hasConcept: () => false,
      focusPlant: () => "The garden is not on screen during the interview.",
    });
    return {
      show_question_card: base.show_question_card,
      open_editor: async (args: Partial<OpenEditorArgs>) => {
        const checked = base.open_editor(args);
        if (checked !== "Editor opened.") return checked;
        return loadProblemRef.current(args);
      },
    };
  }, []);

  const conversation = useConversation({
    clientTools: tools,
    onAudioAlignment: (alignment) => {
      lipSync.pushAlignment(fromAgentAlignment(alignment), clock.current.offsetForChunk());
    },
    onInterruption: () => {
      lipSync.reset();
      clock.current.reset();
    },
    onModeChange: ({ mode }) => {
      if (mode === "listening") clock.current.reset();
    },
    onMessage: ({ message, role }) => {
      const text = message.replace(/\s+/g, " ").trim().slice(0, 400);
      setCaptions((c) => (role === "user" ? { ...c, user: text } : { ...c, agent: text }));
    },
    onDisconnect: () => {
      lipSync.reset();
      sync.current?.flush();
      if (phaseRef.current === "live") {
        setPhaseBoth("interrupted");
        if (sessionId.current) void endSession(sessionId.current, "interrupted");
      }
    },
    onError: (message) => setError(message || "The voice connection failed."),
  });
  useEffect(() => {
    conversationRef.current = conversation;
  });

  // Mouth-level fallback while the agent talks and no alignment is playing.
  const outputVolume = conversation.getOutputVolume;
  const speaking = conversation.isSpeaking;
  useEffect(() => {
    if (phase !== "live" || !speaking) {
      lipSync.setLevel(0);
      return;
    }
    let frame = 0;
    const tick = () => {
      lipSync.setLevel(outputVolume());
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(frame);
      lipSync.setLevel(0);
    };
  }, [phase, speaking, outputVolume, lipSync]);

  // Autosave the code and keep the interviewer's view of the editor current.
  const problemId = problem?.id ?? null;
  const editorLanguage = problem?.language ?? null;
  useEffect(() => {
    if (phase !== "live" || !problemId || !editorLanguage || !sessionId.current) return;
    const id = sessionId.current;
    const s = createCodeSync(
      {
        save: (code) => void saveCode({ sessionId: id, problemId, language: editorLanguage, code }),
        push: (text) => conversationRef.current?.sendContextualUpdate(text),
        now: wallClock,
        setTimer: (fn, ms) => window.setTimeout(fn, ms),
        clearTimer: (h) => window.clearTimeout(h as number),
      },
      { problemId, language: editorLanguage },
    );
    sync.current = s;
    return () => {
      s.flush();
      s.dispose();
      if (sync.current === s) sync.current = null;
    };
  }, [phase, problemId, editorLanguage]);

  // Poll for the tests Arjuna ran, so the results panel updates without a refresh.
  const runsRef = useRef(runs);
  useEffect(() => {
    runsRef.current = runs;
  });
  useEffect(() => {
    if (phase !== "live" && phase !== "ended") return;
    const id = sessionId.current;
    if (!id) return;
    let stopped = false;
    const poll = async () => {
      const fresh = await listRuns(id, pollCursor(runsRef.current));
      if (!stopped && fresh.length) setRuns((prev) => mergeRuns(prev, fresh));
    };
    const timer = window.setInterval(poll, RUN_POLL_MS);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [phase]);

  async function begin() {
    setError(null);
    setPhaseBoth("starting");
    dispatch({ type: "reset" });
    setProblem(null);
    setRuns([]);
    drafts.current.clear();
    const result = await startArjunaSession({ language, concept: initialConcept });
    if (!result.ok) {
      setError(result.message);
      setPhaseBoth("idle");
      return;
    }
    const session = result.data;
    sessionId.current = session.session_id;
    setPlan(session.plan);
    try {
      conversation.startSession({
        conversationToken: session.conversation_token,
        connectionType: "webrtc",
        dynamicVariables: session.dynamic_variables,
        onConnect: ({ conversationId }: { conversationId?: string }) => {
          setStartedAt(Date.now());
          setPhaseBoth("live");
          if (!session.conversation_id && conversationId) {
            void bindConversation(session.session_id, conversationId);
          }
        },
      });
    } catch {
      setError("Could not start the voice connection. Check microphone access and try again.");
      setPhaseBoth("idle");
    }
  }

  function finish() {
    sync.current?.flush();
    conversation.endSession();
    lipSync.reset();
    setPhaseBoth("ended");
    if (sessionId.current) void endSession(sessionId.current, "completed");
  }

  const draftKey = problem ? `${problem.id}:${problem.language}` : "";
  const onCodeChange = useCallback(
    (code: string) => {
      drafts.current.set(draftKey, code);
      sync.current?.update(code);
    },
    [draftKey],
  );
  const onLanguageChange = useCallback(
    async (next: RunnableLanguage) => {
      if (!problem) return;
      sync.current?.flush();
      await loadProblemRef.current({ problem_id: problem.id, language: next });
    },
    [problem],
  );
  const fetchScribeToken = useCallback(async () => {
    const r = await getScribeToken();
    return r.ok
      ? ({ ok: true, token: r.data.token, modelId: r.data.model_id } as const)
      : ({ ok: false, message: r.message } as const);
  }, []);

  const inCall = phase === "live";
  const busy = phase === "starting";
  const problemRuns = problem ? runs.filter((r) => r.problem_id === problem.id) : [];
  const latest = problem ? latestRunFor(runs, problem.id) : null;

  return (
    <main className="mx-auto flex w-full max-w-[1400px] flex-1 flex-col gap-4 px-4 pb-16 pt-24 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-glow">Technical interview</p>
          <h1 className="mt-1 text-2xl font-semibold sm:text-3xl">Interview with Arjuna</h1>
        </div>
        <span
          className={`rounded-full px-2.5 py-1 text-xs ring-1 ${live.connected ? "text-moss ring-moss/40" : "text-foreground/60 ring-white/15"}`}
        >
          {live.connected ? "Live garden updates on" : "Live updates idle"}
        </span>
      </header>

      {error && (
        <p
          role="alert"
          className="rounded-xl border border-ember/40 bg-ember/10 px-4 py-2 text-sm text-ember"
        >
          {error}
        </p>
      )}
      {phase === "interrupted" && (
        <p role="status" className="rounded-xl bg-white/5 px-4 py-2 text-sm">
          The connection dropped. Your code and what you said so far are kept, and they will still
          be checked.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div className="flex flex-col gap-3">
          <div
            className="relative h-72 overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-b from-dusk to-night"
            data-testid="avatar-stage"
          >
            <AvatarSlot driver={lipSync} vrmUrl={vrmUrl} />
            <span
              className="absolute left-3 top-3 rounded-full bg-night/70 px-2.5 py-1 text-xs backdrop-blur"
              role="status"
            >
              {busy
                ? "Connecting…"
                : inCall
                  ? conversation.isSpeaking
                    ? "Arjuna is speaking"
                    : "Listening"
                  : "Arjuna"}
            </span>
          </div>

          {!inCall && phase !== "ended" && (
            <fieldset className="rounded-2xl border border-white/10 p-3">
              <legend className="px-1 text-xs text-foreground/60">Language for coding</legend>
              <div className="flex gap-4 text-sm">
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
            </fieldset>
          )}

          <div className="flex flex-wrap gap-2">
            {!inCall ? (
              <button
                type="button"
                onClick={begin}
                disabled={busy}
                className="rounded-xl bg-glow/90 px-5 py-2.5 text-sm font-medium text-night outline-none hover:bg-glow focus-visible:ring-2 focus-visible:ring-glow disabled:opacity-50"
              >
                {busy
                  ? "Starting…"
                  : phase === "ended" || phase === "interrupted"
                    ? "Start again"
                    : "Start interview"}
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={finish}
                  className="rounded-xl bg-ember/90 px-5 py-2.5 text-sm font-medium text-night outline-none hover:bg-ember focus-visible:ring-2 focus-visible:ring-ember"
                >
                  End interview
                </button>
                <button
                  type="button"
                  onClick={() => conversation.setMuted(!conversation.isMuted)}
                  aria-pressed={conversation.isMuted}
                  className="rounded-xl border border-white/15 px-4 py-2.5 text-sm outline-none hover:border-white/30 focus-visible:ring-2 focus-visible:ring-glow"
                >
                  {conversation.isMuted ? "Unmute" : "Mute"}
                </button>
              </>
            )}
          </div>

          <Captions agent={captions.agent} user={captions.user} speaker="Arjuna" />
          <ThinkAloud active={inCall} startedAt={startedAt} fetchToken={fetchScribeToken} />
        </div>

        <div className="flex min-w-0 flex-col gap-3">
          {!inCall && phase !== "ended" && plan && <PlanCard plan={plan} />}
          {stage.card && (
            <QuestionCardView
              card={stage.card}
              onClose={() => dispatch({ type: "dismiss", what: "card" })}
            />
          )}
          {problem ? (
            <Workbench
              key={draftKey}
              problem={problem}
              language={problem.language}
              initialCode={initialCode}
              runs={problemRuns}
              canRun={inCall}
              onCodeChange={onCodeChange}
              onLanguageChange={onLanguageChange}
              onRunExamples={async (code) => {
                const id = sessionId.current;
                if (!id) return { ok: false, message: "Start the interview first." };
                sync.current?.flush();
                const result = await runExamples({
                  sessionId: id,
                  problemId: problem.id,
                  language,
                  code,
                });
                return result.ok ? { ok: true, data: result.data } : result;
              }}
              onClose={() => setProblem(null)}
            />
          ) : (
            inCall && (
              <p className="glass rounded-2xl p-5 text-sm text-foreground/70">
                The editor opens when Arjuna gives you a problem. Until then, talk through your
                background and how you approach problems.
              </p>
            )
          )}
          {latest === null && problem && inCall && (
            <p className="text-xs text-foreground/50">
              Arjuna runs the full tests when you say you are ready.
            </p>
          )}
          <EvidenceTicker entries={stage.ticker} />
          {phase === "ended" && (
            <p role="status" className="rounded-xl bg-white/5 px-4 py-3 text-sm">
              Interview saved. Your answers and test results are being checked, and your garden will
              update within about half a minute. Hints Arjuna gave are recorded, and anything solved
              after a hint counts as assisted.{" "}
              <Link href="/garden" className="text-glow underline underline-offset-2">
                Open your garden
              </Link>
            </p>
          )}
        </div>
      </div>
    </main>
  );
}
