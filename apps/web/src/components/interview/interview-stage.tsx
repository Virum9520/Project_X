"use client";

import { ConversationProvider, useConversation } from "@elevenlabs/react";
import type { GardenDataset, LiveGrowthEvent } from "@sg/contracts";
import { fromAgentAlignment, useLipSync } from "@sg/three/avatar";
import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";

import { bindConversation, endSession } from "@/app/(app)/session/actions";
import { sendDeliverySummary, startInterviewSession } from "@/app/(app)/interview/actions";
import { AvatarSlot } from "@/components/session/avatar-slot";
import {
  CallControls,
  ErrorBanner,
  SavedNotice,
  StageHeader,
  StagePanels,
  StatusNote,
  useMouthLevelFallback,
  usePhase,
} from "@/components/session/stage-chrome";
import { Captions, EvidenceTicker } from "@/components/session/stage-parts";
import { PaceTracker } from "@/lib/interview/delivery";
import { INITIAL_DIRECTOR, directorReducer, shotWeight, type Shot } from "@/lib/interview/director";
import { plainText, speakerOfMessage, type PanelSpeaker } from "@/lib/interview/speaker";
import { useDeliveryObserver } from "@/lib/interview/use-delivery-observer";
import { AlignmentClock } from "@/lib/session/alignment-clock";
import { INITIAL_STAGE, createStageTools, stageReducer } from "@/lib/session/stage";
import { useLiveGrowth } from "@/lib/session/use-live-growth";

export interface InterviewStageProps {
  mode: "hr" | "panel";
  dataset: GardenDataset;
  isMock: boolean;
  viduraVrmUrl?: string;
  arjunaVrmUrl?: string;
}

const NAMES: Record<PanelSpeaker, string> = { vidura: "Vidura", arjuna: "Arjuna" };
const wallClock = () => Date.now();

export function InterviewStage(props: InterviewStageProps) {
  return (
    <ConversationProvider>
      <Stage {...props} />
    </ConversationProvider>
  );
}

function Stage({ mode, dataset, isMock, viduraVrmUrl, arjunaVrmUrl }: InterviewStageProps) {
  const panel = mode === "panel";
  const viduraSync = useLipSync();
  const arjunaSync = useLipSync();
  const clock = useRef(new AlignmentClock());
  const speaker = useRef<PanelSpeaker>("vidura");
  const pace = useRef(new PaceTracker());
  const sessionId = useRef<string | null>(null);
  const [stage, dispatch] = useReducer(stageReducer, INITIAL_STAGE);
  const [director, direct] = useReducer(directorReducer, INITIAL_DIRECTOR);
  const { phase, phaseRef, setPhaseBoth } = usePhase();
  const [error, setError] = useState<string | null>(null);
  const [captions, setCaptions] = useState({ agent: "", user: "" });
  const [talking, setTalking] = useState<PanelSpeaker | null>(null);
  const [consent, setConsent] = useState(false);
  const {
    status: cameraStatus,
    attachVideo,
    start: startCamera,
    stop: stopCamera,
    summary: cameraSummary,
  } = useDeliveryObserver();

  const live = useLiveGrowth({
    enabled: phase === "live" || phase === "ended",
    onEvent: useCallback((e: LiveGrowthEvent) => dispatch({ type: "growth", event: e }), []),
  });

  const conceptKeys = useMemo(() => new Set(dataset.plants.map((p) => p.key)), [dataset.plants]);
  const tools = useMemo(
    () =>
      createStageTools({
        dispatch,
        now: wallClock,
        hasConcept: (key) => conceptKeys.has(key),
        // The interview stage has no garden camera; the tool answers politely.
        focusPlant: () => "The garden is not on screen during an interview.",
      }),
    [conceptKeys],
  );
  const driverFor = useCallback(
    (who: PanelSpeaker) => (panel && who === "arjuna" ? arjunaSync : viduraSync),
    [panel, arjunaSync, viduraSync],
  );

  const conversation = useConversation({
    clientTools: tools,
    onAudioAlignment: (alignment) => {
      driverFor(speaker.current).pushAlignment(
        fromAgentAlignment(alignment),
        clock.current.offsetForChunk(),
      );
    },
    onInterruption: () => {
      viduraSync.reset();
      arjunaSync.reset();
      clock.current.reset();
    },
    onModeChange: ({ mode: m }) => {
      if (m === "listening") {
        clock.current.reset();
        pace.current.markListening(Date.now());
        setTalking(null);
        direct({ type: "candidate_turn", now: Date.now() });
      } else {
        setTalking(speaker.current);
        direct({ type: "agent_speaking", speaker: speaker.current, now: Date.now() });
      }
    },
    onMessage: (payload) => {
      const { message, role } = payload;
      if (role === "user") {
        const text = message.replace(/\s+/g, " ").trim().slice(0, 400);
        pace.current.onLearnerMessage(text, Date.now());
        setCaptions((c) => ({ ...c, user: text }));
        return;
      }
      const who = panel ? speakerOfMessage(payload, speaker.current) : "vidura";
      speaker.current = who;
      setTalking(who);
      direct({ type: "agent_speaking", speaker: who, now: Date.now() });
      setCaptions((c) => ({ ...c, agent: plainText(message).slice(0, 400) }));
    },
    onDisconnect: () => {
      viduraSync.reset();
      arjunaSync.reset();
      if (phaseRef.current === "live") {
        setPhaseBoth("interrupted");
        void conclude("interrupted");
      }
    },
    onError: (message) => setError(message || "The voice connection failed."),
  });

  // Mouth-level fallback for whoever is speaking while no alignment is playing.
  const drivers = useMemo(() => [viduraSync, arjunaSync], [viduraSync, arjunaSync]);
  const pickDriver = useCallback(() => driverFor(speaker.current), [driverFor]);
  useMouthLevelFallback({
    live: phase === "live",
    speaking: conversation.isSpeaking,
    outputVolume: conversation.getOutputVolume,
    drivers,
    pick: pickDriver,
  });

  // Apply a camera cut that was held back by the minimum dwell.
  useEffect(() => {
    if (!director.pending) return;
    const id = window.setTimeout(() => direct({ type: "tick", now: Date.now() }), 400);
    return () => window.clearTimeout(id);
  }, [director]);

  async function conclude(status: "completed" | "interrupted") {
    const id = sessionId.current;
    // Delivery notes go out only when the learner opted in and the camera actually ran.
    const summary = cameraStatus === "on" ? cameraSummary(pace.current.wpm) : null;
    stopCamera();
    if (!id) return;
    if (consent && summary) await sendDeliverySummary(id, summary).catch(() => undefined);
    await endSession(id, status);
  }

  async function begin() {
    setError(null);
    setPhaseBoth("starting");
    dispatch({ type: "reset" });
    direct({ type: "reset" });
    pace.current = new PaceTracker();
    speaker.current = "vidura";
    if (consent) await startCamera();
    const result = await startInterviewSession({ mode });
    if (!result.ok) {
      stopCamera();
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
      stopCamera();
      setError("Could not start the voice connection. Check microphone access and try again.");
      setPhaseBoth("idle");
    }
  }

  function finish() {
    conversation.endSession();
    viduraSync.reset();
    arjunaSync.reset();
    setPhaseBoth("ended");
    void conclude("completed");
  }

  const inCall = phase === "live";
  const busy = phase === "starting";
  const title = panel ? "Panel interview" : "HR interview with Vidura";
  const status = (who: PanelSpeaker) =>
    talking === who && inCall ? `${NAMES[who]} is speaking` : NAMES[who];
  const people: { who: PanelSpeaker; sync: typeof viduraSync; vrm?: string }[] = panel
    ? [
        { who: "vidura", sync: viduraSync, vrm: viduraVrmUrl },
        { who: "arjuna", sync: arjunaSync, vrm: arjunaVrmUrl },
      ]
    : [{ who: "vidura", sync: viduraSync, vrm: viduraVrmUrl }];
  const shot: Shot = panel ? director.shot : "vidura";

  return (
    <main className="mx-auto flex w-full max-w-[1100px] flex-1 flex-col gap-4 px-4 pb-16 pt-24 sm:px-6">
      <StageHeader
        eyebrow="Interview practice"
        title={title}
        isMock={isMock}
        liveConnected={live.connected}
      />

      <ErrorBanner message={error} />
      {cameraStatus === "denied" && (
        <StatusNote>
          Camera access was declined, so there will be no delivery notes. The interview is
          unaffected.
        </StatusNote>
      )}
      {phase === "interrupted" && (
        <StatusNote>
          The connection dropped. What you said so far is kept, and it will still be checked.
        </StatusNote>
      )}

      <div
        className="flex h-80 gap-3 sm:h-96"
        data-testid="avatar-stage"
        data-shot={shot}
        aria-label={panel ? "Interview panel" : "Interviewer"}
      >
        {people.map(({ who, sync, vrm }) => (
          <div
            key={who}
            className="relative min-w-0 overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-b from-dusk to-night transition-[flex-grow] duration-700 ease-out"
            style={{ flexGrow: panel ? shotWeight(shot, who) : 1, flexBasis: 0 }}
            data-speaker={who}
          >
            <AvatarSlot driver={sync} vrmUrl={vrm} />
            <span
              className={`absolute left-3 top-3 rounded-full px-2.5 py-1 text-xs backdrop-blur ${
                talking === who && inCall ? "bg-glow/80 text-night" : "bg-night/70"
              }`}
              role="status"
            >
              {phase === "starting" ? "Connecting…" : status(who)}
            </span>
          </div>
        ))}
      </div>

      <div className="flex flex-wrap items-start gap-3">
        <CallControls
          noun="interview"
          phase={phase}
          isMuted={conversation.isMuted}
          onStart={begin}
          onEnd={finish}
          onToggleMute={() => conversation.setMuted(!conversation.isMuted)}
        />

        <fieldset
          className="min-w-[16rem] flex-1 rounded-xl border border-white/10 p-3 text-sm"
          disabled={inCall || busy}
        >
          <legend className="px-1 text-xs uppercase tracking-[0.2em] text-foreground/60">
            Optional delivery notes
          </legend>
          <label className="flex items-start gap-2">
            <input
              type="checkbox"
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              className="mt-1"
            />
            <span>
              Use my camera during the interview to note framing, facing the camera and speaking
              pace. Video stays in this browser; only three summary numbers are saved. This says
              nothing about honesty, personality or ability.
            </span>
          </label>
        </fieldset>
      </div>

      <video
        ref={attachVideo}
        muted
        playsInline
        aria-label="Your camera preview"
        className={`h-24 w-32 -scale-x-100 rounded-lg border border-white/10 object-cover ${
          cameraStatus === "on" ? "" : "hidden"
        }`}
      />

      <Captions agent={captions.agent} user={captions.user} />

      <StagePanels stage={stage} onDismiss={(what) => dispatch({ type: "dismiss", what })} />
      <EvidenceTicker entries={stage.ticker} />
      {phase === "ended" && (
        <SavedNotice>
          Interview saved. Your answers are being checked; feedback on your communication appears in
          your memory panel and any technical growth in your garden within about half a minute.
        </SavedNotice>
      )}
    </main>
  );
}
