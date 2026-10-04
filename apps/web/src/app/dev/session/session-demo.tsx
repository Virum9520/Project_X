"use client";

import type { GardenDataset, LiveGrowthEvent } from "@sg/contracts";
import { mockAlignment, useLipSync } from "@sg/three/avatar";
import { useMemo, useReducer, useState } from "react";

import { AvatarSlot } from "@/components/session/avatar-slot";
import { GardenSceneSlot } from "@/components/garden/garden-scene-slot";
import {
  Captions,
  DiagramPlaceholder,
  EditorPlaceholder,
  EvidenceTicker,
  QuestionCardView,
  TeachBackPanel,
} from "@/components/session/stage-parts";
import { useGardenDashboard } from "@/components/garden/use-garden-dashboard";
import { DEFAULT_STATE } from "@/lib/garden/state";
import {
  INITIAL_STAGE,
  createStageTools,
  pulseConceptIds,
  stageReducer,
} from "@/lib/session/stage";

const CONCEPT = "dsa.binary_search";
const wallClock = () => Date.now();

/**
 * The voice stage with no ElevenLabs and no API: buttons stand in for what Drona does (client
 * tools, speech alignment) and for the SSE growth events, so the UI can be worked on offline.
 */
export function SessionDemo({ dataset }: { dataset: GardenDataset }) {
  const lipSync = useLipSync();
  const garden = useGardenDashboard(dataset, DEFAULT_STATE);
  const [stage, dispatch] = useReducer(stageReducer, INITIAL_STAGE);
  const [pulse, setPulse] = useState<ReadonlySet<string>>(new Set());
  const concept = dataset.plants[0]?.key ?? CONCEPT;
  const tools = useMemo(
    () =>
      createStageTools({
        dispatch,
        now: wallClock,
        hasConcept: (k) => dataset.plants.some((p) => p.key === k),
        focusPlant: garden.clientTools.focus_plant,
      }),
    [dataset.plants, garden.clientTools.focus_plant],
  );

  function grow(kind: LiveGrowthEvent["kind"], assisted = false) {
    const event: LiveGrowthEvent = {
      id: crypto.randomUUID(),
      kind,
      sessionId: "demo",
      conceptId: concept,
      questionId: null,
      dimension: "explanation",
      part: "roots",
      outcome: "demonstrated",
      assisted,
      quote: "It halves the sorted range each step.",
      note: "",
      judge: "demo",
      reason: kind === "retracted" ? "The answer leaned on a hint, so it counts as assisted." : "",
      occurredAt: new Date().toISOString(),
    };
    dispatch({ type: "growth", event });
    if (kind !== "noted") {
      setPulse(new Set([concept]));
      window.setTimeout(() => setPulse(new Set()), 6000);
    }
  }

  function speak() {
    lipSync.reset();
    lipSync.start();
    lipSync.pushAlignment(mockAlignment("So tell me, why must the list be sorted first?", 65));
  }

  const btn = "rounded-lg border border-white/15 px-3 py-1.5 text-sm hover:border-white/30";
  return (
    <main className="mx-auto flex max-w-[1400px] flex-col gap-4 px-4 pb-16 pt-24">
      <h1 className="text-2xl font-semibold">Voice stage demo (mock)</h1>
      <div className="flex flex-wrap gap-2">
        <button className={btn} onClick={speak}>
          Drona speaks
        </button>
        <button
          className={btn}
          onClick={() =>
            tools.show_question_card({
              question_id: `concept_check:${concept}:0`,
              title: "Why sorted?",
              body: "In your own words, why must the input be sorted for binary search?",
            })
          }
        >
          show_question_card
        </button>
        <button
          className={btn}
          onClick={() =>
            tools.show_question_card({
              question_id: `teach_back:${concept}:0`,
              title: "Teach me",
              body: "Pretend I'm a first-year student. Teach me binary search.",
            })
          }
        >
          Teach-back card
        </button>
        <button className={btn} onClick={() => tools.highlight_plant({ concept_id: concept })}>
          highlight_plant
        </button>
        <button
          className={btn}
          onClick={() => tools.focus_plant({ level: "plant", target_id: concept })}
        >
          focus_plant
        </button>
        <button
          className={btn}
          onClick={() => tools.open_editor({ problem_id: "p1", language: "python" })}
        >
          open_editor
        </button>
        <button
          className={btn}
          onClick={() =>
            tools.show_diagram({ diagram_id: "bs_trace", caption: "Halving the range" })
          }
        >
          show_diagram
        </button>
        <button className={btn} onClick={() => grow("provisional")}>
          SSE: provisional
        </button>
        <button className={btn} onClick={() => grow("provisional", true)}>
          SSE: provisional (assisted)
        </button>
        <button className={btn} onClick={() => grow("confirmed")}>
          SSE: confirmed
        </button>
        <button className={btn} onClick={() => grow("retracted")}>
          SSE: retracted
        </button>
      </div>
      <div className="grid gap-4 lg:grid-cols-[22rem_1fr]">
        <div className="flex flex-col gap-3">
          <div className="h-72 overflow-hidden rounded-2xl border border-white/10 bg-gradient-to-b from-dusk to-night">
            <AvatarSlot driver={lipSync} />
          </div>
          <Captions
            agent="So tell me, why must the list be sorted first?"
            user="Because we halve the range."
          />
          {stage.teachBack && (
            <TeachBackPanel
              startedAt={stage.teachBackStartedAt}
              heard="It halves the sorted range each step."
              onDone={() => dispatch({ type: "endTeachBack" })}
              disabled={false}
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
            focus={garden.state.focus}
            onFocusChange={garden.actions.focusOn}
            asOf={new Date(garden.view.cutoff).toISOString()}
            isTimeTravel={false}
            recentGrowthPlantKeys={[...pulseConceptIds(stage, pulse, 0)]}
            evidence={garden.view.evidence}
            prerequisites={dataset.prerequisites}
            revision={0}
            ruleVersion={dataset.freshness.rulesVersion}
          />
          <EvidenceTicker entries={stage.ticker} />
        </div>
      </div>
    </main>
  );
}
