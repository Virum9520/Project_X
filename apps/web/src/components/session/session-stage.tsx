"use client";

import "@/lib/voice/quiet-livekit";
import { ConversationProvider, useConversation } from "@elevenlabs/react";
import type { GardenDataset, LiveGrowthEvent } from "@sg/contracts";
import { fromAgentAlignment, useLipSync } from "@sg/three/avatar";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { bindConversation, endSession, startDronaSession } from "@/app/(app)/session/actions";
import { GardenSceneSlot } from "@/components/garden/garden-scene-slot";
import { useGardenDashboard } from "@/components/garden/use-garden-dashboard";
import { useGardenAudioState } from "@/components/soundscape/audio-state";
import { SoundControls } from "@/components/soundscape/sound-controls";
import { SoundscapeProvider } from "@/components/soundscape/soundscape-provider";
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
  CallControls,
  ErrorBanner,
  SavedNotice,
  StageHeader,
  StagePanels,
  StatusNote,
  useMouthLevelFallback,
  usePhase,
} from "./stage-chrome";
import { Captions, EvidenceTicker, TeachBackPanel } from "./stage-parts";
import { useSessionCues } from "./use-session-cues";

const wallClock = () => Date.now();

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

function Stage(props: SessionStageProps) {
  const garden = useGardenDashboard(props.dataset, DEFAULT_STATE);
  const audio = useGardenAudioState(garden.view.plants);
  return (
    <SoundscapeProvider garden={audio}>
      <StageBody {...props} garden={garden} />
    </SoundscapeProvider>
  );
}

function StageBody({
  dataset,
  isMock,
  initialConcept,
  initialMode,
  vrmUrl,
  garden,
}: SessionStageProps & { garden: ReturnType<typeof useGardenDashboard> }) {
  const lipSync = useLipSync();
  const clock = useRef(new AlignmentClock());
  const { onGrowth, reset: resetCues } = useSessionCues();
  const [stage, dispatch] = useReducer(stageReducer, INITIAL_STAGE);
  const { phase, phaseRef, setPhaseBoth } = usePhase();
  const [error, setError] = useState<string | null>(null);
  const [captions, setCaptions] = useState({ agent: "", user: "" });
  const sessionId = useRef<string | null>(null);

  const live = useLiveGrowth({
    enabled: phase === "live" || phase === "ended",
    onEvent: useCallback(
      (e: LiveGrowthEvent) => {
        dispatch({ type: "growth", event: e });
        onGrowth(e);
      },
      [onGrowth],
    ),
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
  const drivers = useMemo(() => [lipSync], [lipSync]);
  const pickDriver = useCallback(() => lipSync, [lipSync]);
  useMouthLevelFallback({
    live: phase === "live",
    speaking: conversation.isSpeaking,
    outputVolume: conversation.getOutputVolume,
    drivers,
    pick: pickDriver,
  });

  async function begin() {
    setError(null);
    setPhaseBoth("starting");
    dispatch({ type: "reset" });
    resetCues();
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
  const inCall = phase === "live";

  return (
    <main className="mx-auto flex w-full max-w-[1400px] flex-1 flex-col gap-4 px-4 pb-16 pt-24 sm:px-6">
      <StageHeader
        eyebrow="Voice session"
        title={
          initialMode === "teach_back" ? "Teach-back with Drona" : "Concept practice with Drona"
        }
        subtitle={initialConcept}
        isMock={isMock}
        liveConnected={live.connected}
        extra={<SoundControls recentGrowthPlantKeys={recentGrowth} />}
      />

      <ErrorBanner message={error} />
      {phase === "interrupted" && (
        <StatusNote>
          The connection dropped. What you showed so far is kept, and it will still be checked.
        </StatusNote>
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
            <CallControls
              noun="session"
              phase={phase}
              isMuted={conversation.isMuted}
              onStart={begin}
              onEnd={finish}
              onToggleMute={() => conversation.setMuted(!conversation.isMuted)}
            />
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
          <StagePanels stage={stage} onDismiss={(what) => dispatch({ type: "dismiss", what })} />
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
            <SavedNotice>
              Session saved. Your answers are being checked and your garden will update within about
              half a minute.
            </SavedNotice>
          )}
        </div>
      </div>
    </main>
  );
}
