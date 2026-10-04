"use client";

import { ConversationProvider, useConversation } from "@elevenlabs/react";
import type { GardenDataset, LiveGrowthEvent } from "@sg/contracts";
import { fromAgentAlignment, useLipSync } from "@sg/three/avatar";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { bindConversation, endSession, startDronaSession } from "@/app/(app)/session/actions";
import { GardenSceneSlot } from "@/components/garden/garden-scene-slot";
import { useGardenDashboard } from "@/components/garden/use-garden-dashboard";
import { AlignmentClock } from "@/lib/session/alignment-clock";
import {
  INITIAL_STAGE,
  PULSE_MS,
  createStageTools,
  pulseConceptIds,
  stageReducer,
} from "@/lib/session/stage";
import { useLiveGrowth } from "@/lib/session/use-live-growth";
import { DEFAULT_STATE } from "@/lib/garden/state";

import { AvatarSlot } from "./avatar-slot";
import {
  Captions,
  DiagramPlaceholder,
  EditorPlaceholder,
  EvidenceTicker,
  QuestionCardView,
  TeachBackPanel,
} from "./stage-parts";

const wallClock = () => Date.now();

type Phase = "idle" | "starting" | "live" | "ended" | "interrupted";

export interface SessionStageProps {
  dataset: GardenDataset;
  isMock: boolean;
  initialConcept?: string;
  initialMode: "concept_exam" | "teach_back";
  vrmUrl?: string;
}

export function SessionStage(props: SessionStageProps) {
  return (
    <ConversationProvider>
      <Stage {...props} />
    </ConversationProvider>
  );
}

function Stage({ dataset, isMock, initialConcept, initialMode, vrmUrl }: SessionStageProps) {
  const lipSync = useLipSync();
  const clock = useRef(new AlignmentClock());
  const garden = useGardenDashboard(dataset, DEFAULT_STATE);
  const [stage, dispatch] = useReducer(stageReducer, INITIAL_STAGE);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [captions, setCaptions] = useState({ agent: "", user: "" });
  const sessionId = useRef<string | null>(null);
  const phaseRef = useRef<Phase>("idle");
  const setPhaseBoth = useCallback((next: Phase) => {
    phaseRef.current = next;
    setPhase(next);
  }, []);

  const live = useLiveGrowth({
    enabled: phase === "live" || phase === "ended",
    onEvent: useCallback((e: LiveGrowthEvent) => dispatch({ type: "growth", event: e }), []),
  });

  const conceptKeys = useMemo(() => new Set(dataset.plants.map((p) => p.key)), [dataset.plants]);
  const {
    focus_plant: focusPlantTool,
    set_filter: setFilterTool,
    scrub_timeline: scrubTool,
  } = garden.clientTools;
  const tools = useMemo(
    () =>
      createStageTools({
        dispatch,
        now: wallClock,
        hasConcept: (key) => conceptKeys.has(key),
        focusPlant: focusPlantTool,
        setFilter: setFilterTool,
        scrubTimeline: scrubTool,
      }),
    [conceptKeys, focusPlantTool, setFilterTool, scrubTool],
  );

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
      if (phaseRef.current === "live") {
        setPhaseBoth("interrupted");
        if (sessionId.current) void endSession(sessionId.current, "interrupted");
      }
    },
    onError: (message) => setError(message || "The voice connection failed."),
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

  async function begin() {
    setError(null);
    setPhaseBoth("starting");
    dispatch({ type: "reset" });
    const result = await startDronaSession({ concept: initialConcept, mode: initialMode });
    if (!result.ok) {
      setError(result.message);
      setPhaseBoth("idle");
      return;
    }
    const session = result.data;
    sessionId.current = session.session_id;
    try {
      conversation.startSession({
        conversationToken: session.conversation_token,
        connectionType: "webrtc",
        dynamicVariables: session.dynamic_variables,
        onConnect: ({ conversationId }: { conversationId?: string }) => {
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
    conversation.endSession();
    lipSync.reset();
    setPhaseBoth("ended");
    if (sessionId.current) void endSession(sessionId.current, "completed");
  }

  function finishTeachBack() {
    conversation.sendUserMessage("That is my whole explanation. I am done teaching.");
    dispatch({ type: "endTeachBack" });
  }

  const focus = garden.state.focus;
  // Re-evaluate when a highlight starts and again when it is due to fade.
  const [clockMs, setClockMs] = useState(0);
  const highlight = stage.highlight;
  useEffect(() => {
    if (!highlight) return;
    const start = window.setTimeout(() => setClockMs(Date.now()), 0);
    const end = window.setTimeout(() => setClockMs(Date.now()), PULSE_MS + 50);
    return () => {
      window.clearTimeout(start);
      window.clearTimeout(end);
    };
  }, [highlight]);
  const recentGrowth = useMemo(
    () => [...pulseConceptIds(stage, live.pulseConceptIds, clockMs)],
    [stage, live.pulseConceptIds, clockMs],
  );
  const revision = useMemo(
    () => dataset.growthEvents.reduce((max, g) => Math.max(max, g.revision), 0),
    [dataset.growthEvents],
  );
  const busy = phase === "starting";
  const inCall = phase === "live";

  return (
    <main className="mx-auto flex w-full max-w-[1400px] flex-1 flex-col gap-4 px-4 pb-16 pt-24 sm:px-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-[0.3em] text-glow">Voice session</p>
          <h1 className="mt-1 text-2xl font-semibold sm:text-3xl">
            {initialMode === "teach_back" ? "Teach-back with Drona" : "Concept practice with Drona"}
          </h1>
          {initialConcept && (
            <p className="mt-1 font-mono text-xs text-foreground/60">{initialConcept}</p>
          )}
        </div>
        <div className="flex items-center gap-2 text-xs text-foreground/60">
          {isMock && (
            <span className="rounded-full bg-ember/15 px-2.5 py-1 text-ember ring-1 ring-ember/40">
              Sample garden
            </span>
          )}
          <span
            className={`rounded-full px-2.5 py-1 ring-1 ${live.connected ? "text-moss ring-moss/40" : "ring-white/15"}`}
          >
            {live.connected ? "Live garden updates on" : "Live updates idle"}
          </span>
        </div>
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
          The connection dropped. What you showed so far is kept, and it will still be checked.
        </p>
      )}

      <div className="grid gap-4 lg:grid-cols-[minmax(0,22rem)_minmax(0,1fr)]">
        <div className="flex flex-col gap-3">
          <div
            className="relative h-80 overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-b from-dusk to-night"
            data-testid="avatar-stage"
          >
            <AvatarSlot driver={lipSync} vrmUrl={vrmUrl} />
            <span
              className="absolute left-3 top-3 rounded-full bg-night/70 px-2.5 py-1 text-xs backdrop-blur"
              role="status"
            >
              {phase === "starting"
                ? "Connecting…"
                : inCall
                  ? conversation.isSpeaking
                    ? "Drona is speaking"
                    : "Listening"
                  : "Drona"}
            </span>
          </div>

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
                    : "Start session"}
              </button>
            ) : (
              <>
                <button
                  type="button"
                  onClick={finish}
                  className="rounded-xl bg-ember/90 px-5 py-2.5 text-sm font-medium text-night outline-none hover:bg-ember focus-visible:ring-2 focus-visible:ring-ember"
                >
                  End session
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

          <Captions agent={captions.agent} user={captions.user} />
          {stage.teachBack && inCall && (
            <TeachBackPanel
              startedAt={stage.teachBackStartedAt}
              heard={captions.user}
              onDone={finishTeachBack}
              disabled={!inCall}
            />
          )}
        </div>

        <div className="flex min-w-0 flex-col gap-3">
          {stage.card && (
            <QuestionCardView
              card={stage.card}
              onClose={() => dispatch({ type: "dismiss", what: "card" })}
            />
          )}
          {stage.editor && (
            <EditorPlaceholder
              problemId={stage.editor.problem_id}
              language={stage.editor.language}
              onClose={() => dispatch({ type: "dismiss", what: "editor" })}
            />
          )}
          {stage.diagram && (
            <DiagramPlaceholder
              id={stage.diagram.id}
              caption={stage.diagram.caption}
              onClose={() => dispatch({ type: "dismiss", what: "diagram" })}
            />
          )}
          <GardenSceneSlot
            groves={dataset.groves}
            plants={garden.view.plants}
            focus={focus}
            onFocusChange={garden.actions.focusOn}
            asOf={new Date(garden.view.cutoff).toISOString()}
            isTimeTravel={garden.view.isPast}
            recentGrowthPlantKeys={recentGrowth}
            evidence={garden.view.evidence}
            prerequisites={dataset.prerequisites}
            revision={revision}
            ruleVersion={dataset.freshness.rulesVersion}
          />
          <EvidenceTicker entries={stage.ticker} />
          {phase === "ended" && (
            <p role="status" className="rounded-xl bg-white/5 px-4 py-3 text-sm">
              Session saved. Your answers are being checked and your garden will update within about
              half a minute.{" "}
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
